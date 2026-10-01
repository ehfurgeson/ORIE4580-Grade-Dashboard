"""One-time migration from descriptive standard keys to S IDs, without source reads.

Run with the refresh service stopped. The input is preserved; output must be a
new private path. Only lab-mapping-v2 / exam1-mapping-v1 caches are supported.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import json
from pathlib import Path
import stat

from sync.checkoff_mappings import LAB_MAPPING_VERSION
from sync.completion_cache import (
    _exam_mapping,
    _fingerprint,
    _lab_mapping,
    exam_contract,
    lab_contract,
    validate_completion_cache,
    write_completion_cache_atomic,
)
from sync.gradescope import AdapterConfig, load_config
from sync.gradescope_exam import EXAM_MAPPING_VERSION


# Legacy serialization only; the live catalog and mappings still use S IDs.
LEGACY_KEYS = {
    'S1': 'uniform_samplers',
    'S2': 'general_1d_sampler',
    'S3': 'simulation_output_variability',
    'S4': 'histogram_parameters',
    'S5': 'confidence_interval_procedures',
}


def _upgrade_wrapper(
    wrapper: object, contract: dict, mapping: list[dict],
    version_field: str, old_version: str,
) -> dict:
    legacy_contract = {**contract, version_field: old_version}
    legacy_mapping = [
        {**{key: value for key, value in row.items() if key != 'standard_id'},
         'standard_key': LEGACY_KEYS[row['standard_id']]}
        for row in mapping
    ]
    expected = {
        'contract': legacy_contract,
        'fingerprint': _fingerprint({
            'contract': legacy_contract, 'effective_mapping': legacy_mapping,
        }),
    }
    if _fingerprint(wrapper) != _fingerprint(expected):
        raise ValueError("Old cache contract or fingerprint does not match this migration")
    return {
        'contract': contract,
        'fingerprint': _fingerprint({'contract': contract, 'effective_mapping': mapping}),
    }


def migrate_cache(value: dict, config: AdapterConfig) -> dict:
    """Preserve completions and timestamps only when the old contracts match."""
    if (LAB_MAPPING_VERSION, EXAM_MAPPING_VERSION) != ('lab-mapping-v3', 'exam1-mapping-v2'):
        raise ValueError("This one-time migration does not support the current mappings")
    result = deepcopy(value)
    try:
        rules = {rule.opportunity_id: rule for rule in config.assignments}
        for opportunity_id, wrapper in result['lab_contracts'].items():
            result['lab_contracts'][opportunity_id] = _upgrade_wrapper(
                wrapper, lab_contract(config, rules[opportunity_id]),
                _lab_mapping(opportunity_id), 'title_mapping_version', 'lab-mapping-v2',
            )
        if result['exam_contract'] is not None:
            result['exam_contract'] = _upgrade_wrapper(
                result['exam_contract'], exam_contract(config), _exam_mapping(),
                'mapping_version', 'exam1-mapping-v1',
            )
        errors = validate_completion_cache(result, config=config)
        if errors:
            raise ValueError("Invalid migrated cache: " + "; ".join(errors))
        if any(entry['opportunity_id'] not in result['lab_contracts'] for entry in result['lab_passes']):
            raise ValueError("A Lab pass has no matching cached contract")
        if result['exam_completions'] and (
            result['exam_contract'] is None or not result['exam_contract']['contract']['rubric_finalized']
        ):
            raise ValueError("Exam completions require a finalized cached contract")
    except (AttributeError, KeyError, TypeError) as error:
        raise ValueError("Invalid cache structure or unconfigured opportunity") from error
    return result


def _unique_fields(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON key")
        result[key] = value
    return result


def _reject_constant(_token: str) -> None:
    raise ValueError("Nonfinite JSON value")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('config', type=Path, help="production Gradescope TOML config")
    parser.add_argument('input', type=Path, help="old private completion cache")
    parser.add_argument('output', type=Path, help="new private cache path (must not exist)")
    args = parser.parse_args()
    try:
        info = args.input.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077 or info.st_size > 16_000_000:
            raise ValueError("Input must be a private regular file, at most 16 MB")
        if args.output.exists() or args.output.is_symlink():
            raise ValueError("Output already exists; choose a new path")
        output = args.output.resolve()
        repository = Path(__file__).resolve().parents[1]
        for public_name in ('static', 'public'):
            public_root = repository / public_name
            if output == public_root or public_root in output.parents:
                raise ValueError("Output must be outside static/ and public/")
        with args.input.open(encoding='utf-8') as handle:
            value = json.load(handle, object_pairs_hook=_unique_fields, parse_constant=_reject_constant)
        cache = migrate_cache(value, load_config(args.config))
        write_completion_cache_atomic(cache, output)
    except (OSError, UnicodeError, ValueError) as error:
        parser.error(str(error))
    print(f"Preserved {len(cache['lab_passes'])} Lab passes and {len(cache['exam_completions'])} Exam completions")


if __name__ == '__main__':
    main()
