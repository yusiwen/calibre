#!/usr/bin/env python
# vim:fileencoding=utf-8
from __future__ import (unicode_literals, division, absolute_import,
                        print_function)

__license__ = 'GPL v3'
__copyright__ = '2014, Kovid Goyal <kovid at kovidgoyal.net>'

import cPickle
from collections import namedtuple

from calibre.utils.localization import canonicalize_lang

DictionaryLocale = namedtuple('DictionaryLocale', 'langcode countrycode')

ccodes, ccodemap, country_names = None, None, None

def get_codes():
    global ccodes, ccodemap, country_names
    if ccodes is None:
        data = cPickle.loads(P('localization/iso3166.pickle', allow_user_override=False, data=True))
        ccodes, ccodemap, country_names = data['codes'], data['three_map'], data['names']
    return ccodes, ccodemap

def parse_lang_code(raw):
    raw = raw or ''
    parts = raw.replace('_', '-').split('-')
    lc = canonicalize_lang(parts[0])
    if lc is None:
        raise ValueError('Invalid language code: %r' % raw)
    cc = None
    if len(parts) > 1:
        ccodes, ccodemap = get_codes()[:2]
        q = parts[1].upper()
        if q in ccodes:
            cc = q
        else:
            cc = ccodemap.get(q, None)
    return DictionaryLocale(lc, cc)


