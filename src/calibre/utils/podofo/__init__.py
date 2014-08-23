#!/usr/bin/env python
# vim:fileencoding=UTF-8:ts=4:sw=4:sta:et:sts=4:ai
from __future__ import with_statement

__license__   = 'GPL v3'
__copyright__ = '2009, Kovid Goyal <kovid@kovidgoyal.net>'
__docformat__ = 'restructuredtext en'

import os, shutil

from calibre.constants import plugins, preferred_encoding
from calibre.ebooks.metadata import authors_to_string
from calibre.ptempfile import TemporaryDirectory
from calibre.utils.ipc.simple_worker import fork_job, WorkerError

def get_podofo():
    podofo, podofo_err = plugins['podofo']
    if podofo is None:
        raise RuntimeError('Failed to load podofo: %s'%podofo_err)
    return podofo

def prep(val):
    if not val:
        return u''
    if not isinstance(val, unicode):
        val = val.decode(preferred_encoding, 'replace')
    return val.strip()

def set_metadata(stream, mi):
    with TemporaryDirectory(u'_podofo_set_metadata') as tdir:
        with open(os.path.join(tdir, u'input.pdf'), 'wb') as f:
            shutil.copyfileobj(stream, f)
        from calibre.ebooks.metadata.xmp import metadata_to_xmp_packet
        xmp_packet = metadata_to_xmp_packet(mi)

        try:
            result = fork_job('calibre.utils.podofo', 'set_metadata_', (tdir,
                mi.title, mi.authors, mi.book_producer, mi.tags, xmp_packet))
            touched = result['result']
        except WorkerError as e:
            raise Exception('Failed to set PDF metadata: %s'%e.orig_tb)
        if touched:
            with open(os.path.join(tdir, u'output.pdf'), 'rb') as f:
                f.seek(0, 2)
                if f.tell() > 100:
                    f.seek(0)
                    stream.seek(0)
                    stream.truncate()
                    shutil.copyfileobj(f, stream)
                    stream.flush()
    stream.seek(0)

def set_metadata_(tdir, title, authors, bkp, tags, xmp_packet):
    podofo = get_podofo()
    os.chdir(tdir)
    p = podofo.PDFDoc()
    p.open(u'input.pdf')
    title = prep(title)
    touched = False
    if title and title != p.title:
        p.title = title
        touched = True

    author = prep(authors_to_string(authors))
    if author and author != p.author:
        p.author = author
        touched = True

    bkp = prep(bkp)
    if bkp and bkp != p.creator:
        p.creator = bkp
        touched = True

    try:
        tags = prep(u', '.join([x.strip() for x in tags if x.strip()]))
        if tags != p.keywords:
            p.keywords = tags
            touched = True
    except:
        pass

    try:
        current_xmp_packet = p.get_xmp_metadata()
        if current_xmp_packet:
            from calibre.ebooks.metadata.xmp import merge_xmp_packet
            xmp_packet = merge_xmp_packet(current_xmp_packet, xmp_packet)
        p.set_xmp_metadata(xmp_packet)
        touched = True
    except:
        pass

    if touched:
        p.save(u'output.pdf')

    return touched

def delete_all_but(path, pages):
    ''' Delete all the pages in the pdf except for the specified ones. Negative
    numbers are counted from the end of the PDF. '''
    podofo = get_podofo()
    p = podofo.PDFDoc()
    with open(path, 'rb') as f:
        raw = f.read()
    p.load(raw)
    total = p.page_count()
    pages = {total + x if x < 0 else x for x in pages}
    for page in xrange(total-1, -1, -1):
        if page not in pages:
            p.delete_page(page)

    with open(path, 'wb') as f:
        f.save_to_fileobj(path)

def get_xmp_metadata(path):
    podofo = get_podofo()
    p = podofo.PDFDoc()
    with open(path, 'rb') as f:
        raw = f.read()
    p.load(raw)
    return p.get_xmp_metadata()

def test_outline(src):
    podofo = get_podofo()
    p = podofo.PDFDoc()
    with open(src, 'rb') as f:
        raw = f.read()
    p.load(raw)
    total = p.page_count()
    root = p.create_outline(u'Table of Contents')
    for i in xrange(0, total):
        root.create(u'Page %d'%i, i, True)
    raw = p.write()
    out = '/tmp/outlined.pdf'
    with open(out, 'wb') as f:
        f.write(raw)
    print 'Outlined PDF:', out

def test_save_to(src, dest):
    podofo = get_podofo()
    p = podofo.PDFDoc()
    with open(src, 'rb') as f:
        raw = f.read()
    p.load(raw)
    with open(dest, 'wb') as out:
        p.save_to_fileobj(out)
        print ('Wrote PDF of size:', out.tell())

def test_podofo():
    from io import BytesIO
    from calibre.ebooks.metadata.book.base import Metadata
    from calibre.ebooks.metadata.xmp import metadata_to_xmp_packet
    raw = b'%PDF-1.1\n%\xc2\xa5\xc2\xb1\xc3\xab\n\n1 0 obj\n  << /Type /Catalog\n     /Pages 2 0 R\n  >>\nendobj\n\n2 0 obj\n  << /Type /Pages\n     /Kids [3 0 R]\n     /Count 1\n     /MediaBox [0 0 300 144]\n  >>\nendobj\n\n3 0 obj\n  <<  /Type /Page\n      /Parent 2 0 R\n      /Resources\n       << /Font\n           << /F1\n               << /Type /Font\n                  /Subtype /Type1\n                  /BaseFont /Times-Roman\n               >>\n           >>\n       >>\n      /Contents 4 0 R\n  >>\nendobj\n\n4 0 obj\n  << /Length 55 >>\nstream\n  BT\n    /F1 18 Tf\n    0 0 Td\n    (Hello World) Tj\n  ET\nendstream\nendobj\n\nxref\n0 5\n0000000000 65535 f \n0000000018 00000 n \n0000000077 00000 n \n0000000178 00000 n \n0000000457 00000 n \ntrailer\n  <<  /Root 1 0 R\n      /Size 5\n  >>\nstartxref\n565\n%%EOF\n'  # noqa
    mi = Metadata(u'title1', [u'author1'])
    xmp_packet = metadata_to_xmp_packet(mi)
    podofo = get_podofo()
    p = podofo.PDFDoc()
    p.load(raw)
    p.title = mi.title
    p.author = mi.authors[0]
    p.set_xmp_metadata(xmp_packet)
    buf = BytesIO()
    p.save_to_fileobj(buf)
    raw = buf.getvalue()
    p = podofo.PDFDoc()
    p.load(raw)
    if (p.title, p.author) != (mi.title, mi.authors[0]):
        raise ValueError('podofo failed to set title and author in Info dict')
    if not p.get_xmp_metadata():
        raise ValueError('podofo failed to write XMP packet')

if __name__ == '__main__':
    import sys
    get_xmp_metadata(sys.argv[-1])
