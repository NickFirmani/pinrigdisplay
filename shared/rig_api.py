"""HTTP observation contract between the stream PC and each rig."""
from .display_contracts.commands import number

OBS_REPORT_PATH = '/api/obs'
OBS_VALID_FOR = 8.


def parse_obs_report(value: object, rig: str) -> tuple[bool | None, float]:
    if (not isinstance(value, dict) or set(value) != {'rig', 'live', 'valid_for'}
            or value['rig'] != rig):
        raise ValueError('OBS report must target this rig with rig, live and valid_for')
    live = value['live']
    if live is not None and type(live) is not bool:
        raise ValueError('live must be true, false or null')
    return live, number(value['valid_for'], 'valid_for', .001, OBS_VALID_FOR)
