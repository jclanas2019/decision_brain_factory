"""Strict TOML configuration, relative to the configuration file."""
import math
from pathlib import Path
import tomllib


def load_project(path):
    path=Path(path).resolve()
    with path.open('rb') as stream: data=tomllib.load(stream)
    if set(data)-{'version','harness'} or type(data.get('version')) is not int or data['version']!=1:
        raise ValueError('project.toml requires version=1 and only [harness]')
    config=data.get('harness',{})
    if not isinstance(config,dict) or set(config)-{'run','suite','output','baseline','min_pass_rate'}:
        raise ValueError('Unknown harness configuration key')
    result={}
    for key,value in config.items():
        if key=='min_pass_rate':
            if type(value) not in (int,float) or not math.isfinite(value) or not 0<=value<=1:
                raise ValueError('min_pass_rate must be a finite number in [0,1]')
            result[key]=float(value)
        else:
            if not isinstance(value,str) or not value.strip():raise ValueError(f'{key} must be a nonempty path')
            result[key]=(path.parent/Path(value)).resolve()
    return result
