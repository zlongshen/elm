from collections import OrderedDict

from gdalconst import GA_ReadOnly
import gdal
import logging
import pandas as pd
import re

from elm.readers.util import BandSpec
from elm.model_selection.util import get_args_kwargs_defaults
from elm.sample_util.util import InvalidSample

logger = logging.getLogger(__name__)

DAY_NIGHT_WORDS = ('day', 'night')
FLAG_WORDS = ('flag', 'indicator')
DAY_NIGHT = []
for f in FLAG_WORDS:
    w1 = "".join(DAY_NIGHT_WORDS)
    w2 = "".join(DAY_NIGHT_WORDS[::-1])
    w3, w4 = DAY_NIGHT_WORDS
    for w in (w1, w2, w3, w4):
        w5, w6 = f + w, w + f
        DAY_NIGHT.extend((w5, w6,))

def _strip_key(k):
    if isinstance(k, str):
        for delim in ('.', '_', '-', ' '):
            k = k.lower().replace(delim,'')
    return k

def match_meta(meta, band_spec):
    '''
    Parmeters
    ---------
    meta: dataset meta information object
    band_spec: BandSpec object

    Returns
    -------
    boolean of whether band_spec matches meta
    '''
    if not isinstance(band_spec, BandSpec):
        raise ValueError('band_spec must be elm.readers.BandSpec object')

    for mkey in meta:
        if bool(re.search(band_spec.search_key, mkey, re.IGNORECASE)):
            if bool(re.search(band_spec.search_value, meta[mkey], re.IGNORECASE)):
                return True
    return False


def example_meta_is_day(filename, d):

    dicts = []
    for k, v in d.items():
        if isinstance(v, dict):
            dicts.append(v)
            continue
        key2 = _strip_key(k)
        if key2 in DAY_NIGHT:
            dayflag = 'day' in key2
            nightflag = 'night' in key2
            if dayflag and nightflag:
                value2 = _strip_key(v)
                return 'day' in value2
            elif dayflag or nightflag:
                return bool(v)
    if dicts:
        return any(example_meta_is_day(filename, d2) for d2 in dicts)
    return False


def get_bands(handle, ds, *band_specs):
    for ds_name, label in ds:
        found_bands = 0
        for band_spec in band_specs:
            subhandle = gdal.Open(ds_name, GA_ReadOnly)
            meta = subhandle.GetMetadata()
            name = match_meta(meta, band_spec)
            if name:
                found_bands += 1
                yield subhandle, meta, name
            else:
                subhandle = None
        if found_bands == len(band_specs):
            break

def _select_from_file_base(filename,
                         band_specs,
                         include_polys=None,
                         metadata_filter=None,
                         filename_filter=None,
                         filename_search=None,
                         dry_run=False,
                         load_meta=None,
                         load_array=None,
                         **kwargs):
    from elm.sample_util.geo_selection import _filter_band_data
    from elm.sample_util.filename_selection import _filename_filter
    keep_file = _filename_filter(filename,
                                 search=filename_search,
                                 func=filename_filter)
    args_required, _, _ = get_args_kwargs_defaults(load_meta)
    if len(args_required) == 1:
        meta = load_meta(filename)
    else:
        meta = load_meta(filename, band_specs)
    if metadata_filter is not None:
        keep_file = metadata_filter(filename, meta)
        if dry_run:
           return keep_file

    # TODO rasterio filter / resample / aggregate
    if dry_run:
        return True
    sample = load_array(filename, meta, band_specs)
    # TODO points in poly
    return sample


def select_from_file(*args, **kwargs):
    return _select_from_file_base(*args, **kwargs)

def include_file(*args, **kwargs):
    kwargs['dry_run'] = True
    return _select_from_file_base(*args, **kwargs)
