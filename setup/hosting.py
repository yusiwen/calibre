#!/usr/bin/env python
# vim:fileencoding=UTF-8:ts=4:sw=4:sta:et:sts=4:ai
from __future__ import (unicode_literals, division, absolute_import,
                        print_function)

__license__   = 'GPL v3'
__copyright__ = '2011, Kovid Goyal <kovid@kovidgoyal.net>'
__docformat__ = 'restructuredtext en'

import os, time, sys, traceback, subprocess, urllib2, re, base64, httplib, shutil, glob, json, mimetypes
from pprint import pprint
from argparse import ArgumentParser, FileType
from subprocess import check_call, CalledProcessError, check_output
from tempfile import NamedTemporaryFile
from collections import OrderedDict

def login_to_google(username, password):  # {{{
    import mechanize
    br = mechanize.Browser()
    br.addheaders = [('User-agent',
        'Mozilla/5.0 (X11; Linux x86_64; rv:9.0) Gecko/20100101 Firefox/9.0')]
    br.set_handle_robots(False)
    br.open('https://accounts.google.com/ServiceLogin?service=code')
    br.select_form(nr=0)
    br.form['Email'] = username
    br.form['Passwd'] = password
    raw = br.submit().read()
    if re.search(br'(?i)<title>.*?Account Settings</title>', raw) is None:
        x = re.search(br'(?is)<title>.*?</title>', raw)
        if x is not None:
            print ('Title of post login page: %s'%x.group())
        # open('/tmp/goog.html', 'wb').write(raw)
        raise ValueError(('Failed to login to google with credentials: %s %s'
            '\nGoogle sometimes requires verification when logging in from a '
            'new IP address. Use lynx to login and supply the verification, '
            'at: lynx -accept_all_cookies https://accounts.google.com/ServiceLogin?service=code')
                %(username, password))
    return br
# }}}

class ReadFileWithProgressReporting(file):  # {{{

    def __init__(self, path, mode='rb'):
        file.__init__(self, path, mode)
        self.seek(0, os.SEEK_END)
        self._total = self.tell()
        self.seek(0)
        self.start_time = time.time()

    def __len__(self):
        return self._total

    def read(self, size):
        data = file.read(self, size)
        if data:
            self.report_progress(len(data))
        return data

    def report_progress(self, size):
        sys.stdout.write(b'\x1b[s')
        sys.stdout.write(b'\x1b[K')
        frac = float(self.tell())/self._total
        mb_pos = self.tell()/float(1024**2)
        mb_tot = self._total/float(1024**2)
        kb_pos = self.tell()/1024.0
        kb_rate = kb_pos/(time.time()-self.start_time)
        bit_rate = kb_rate * 1024
        eta = int((self._total - self.tell())/bit_rate) + 1
        eta_m, eta_s = eta / 60, eta % 60
        sys.stdout.write(
            '  %.1f%%   %.1f/%.1fMB %.1f KB/sec    %d minutes, %d seconds left'%(
                frac*100, mb_pos, mb_tot, kb_rate, eta_m, eta_s))
        sys.stdout.write(b'\x1b[u')
        if self.tell() >= self._total:
            sys.stdout.write('\n')
            t = int(time.time() - self.start_time) + 1
            print ('Upload took %d minutes and %d seconds at %.1f KB/sec' % (
                t/60, t%60, kb_rate))
        sys.stdout.flush()
# }}}

class Base(object):  # {{{

    def __init__(self):
        self.d = os.path.dirname
        self.j = os.path.join
        self.a = os.path.abspath
        self.b = os.path.basename
        self.s = os.path.splitext
        self.e = os.path.exists

    def info(self, *args, **kwargs):
        print(*args, **kwargs)
        sys.stdout.flush()

    def warn(self, *args, **kwargs):
        print('\n'+'_'*20, 'WARNING','_'*20)
        print(*args, **kwargs)
        print('_'*50)
        sys.stdout.flush()

# }}}

class GoogleCode(Base):  # {{{

    def __init__(self,
            # A mapping of filenames to file descriptions. The descriptions are
            # used to populate the description field for the upload on google
            # code
            files,

            # The unix name for the application.
            appname,

            # The version being uploaded
            version,

            # Google account username
            username,

            # Googlecode.com password
            password,

            # Google account password
            gmail_password,

            # The name of the google code project we are uploading to
            gc_project,

            # Server to which to upload the mapping of file names to google
            # code URLs. If not None, upload is performed via shelling out to
            # ssh, so you must have ssh-agent setup with the authenticated key
            # and ssh agent forwarding enabled
            gpaths_server=None,
            # The path on gpaths_server to which to upload the mapping data
            gpaths=None,

            # If True, files are replaced, otherwise existing files are skipped
            reupload=False,

            # The pattern to match filenames for the files being uploaded and
            # extract version information from them. Must have a named group
            # named version
            filename_pattern=r'{appname}-(?:portable-installer-)?(?P<version>.+?)(?:-(?:i686|x86_64|32bit|64bit))?\.(?:zip|exe|msi|dmg|tar\.bz2|tar\.xz|txz|tbz2)'  # noqa

            ):
        self.username, self.password, = username, password
        self.gmail_password, self.gc_project = gmail_password, gc_project
        self.reupload, self.files, self.version = reupload, files, version
        self.gpaths, self.gpaths_server = gpaths, gpaths_server

        self.upload_host = '%s.googlecode.com'%gc_project
        self.files_list = 'http://code.google.com/p/%s/downloads/list'%gc_project
        self.delete_url = 'http://code.google.com/p/%s/downloads/delete?name=%%s'%gc_project

        self.filename_pat = re.compile(filename_pattern.format(appname=appname))
        for x in self.files:
            if self.filename_pat.match(os.path.basename(x)) is None:
                raise ValueError(('The filename %s does not match the '
                        'filename pattern')%os.path.basename(x))

    def upload_one(self, fname, retries=2):
        self.info('\nUploading', fname)
        typ = 'Type-' + ('Source' if fname.endswith('.xz') else 'Archive' if
                fname.endswith('.zip') else 'Installer')
        ext = os.path.splitext(fname)[1][1:]
        op  = 'OpSys-'+{'msi':'Windows','exe':'Windows',
                'dmg':'OSX','txz':'Linux','xz':'All'}[ext]
        desc = self.files[fname]
        start = time.time()
        for i in range(retries):
            try:
                path = self.upload(os.path.abspath(fname), desc,
                    labels=[typ, op, 'Featured'], retry=100)
            except KeyboardInterrupt:
                raise SystemExit(1)
            except:
                traceback.print_exc()
                print ('\nUpload failed, trying again in 30 secs.',
                        '%d retries left.'%(retries-1))
                time.sleep(30)
            else:
                break
        self.info('Uploaded to:', path, 'in', int(time.time() - start),
                'seconds')
        return path

    def re_upload(self):
        fnames = {os.path.basename(x):x for x in self.files}
        existing = self.old_files.intersection(set(fnames))
        br = self.login_to_google()
        for x, src in fnames.iteritems():
            if not os.access(src, os.R_OK):
                continue
            if x in existing:
                self.info('Deleting', x)
                br.open(self.delete_url%x)
                br.select_form(predicate=lambda y: 'delete.do' in y.action)
                br.form.find_control(name='delete')
                br.submit(name='delete')
            self.upload_one(src)

    def __call__(self):
        self.paths = {}
        self.old_files = self.get_old_files()
        if self.reupload:
            return self.re_upload()

        for fname in self.files:
            bname = os.path.basename(fname)
            if bname in self.old_files:
                path = 'http://%s.googlecode.com/files/%s'%(self.gc_project,
                        bname)
                self.info(
                    '%s already uploaded, skipping. Assuming URL is: %s'%(
                        bname, path))
                self.old_files.remove(bname)
            else:
                path = self.upload_one(fname)
            self.paths[bname] = path
        self.info('Updating path map')
        for k, v in self.paths.iteritems():
            self.info('\t%s => %s'%(k, v))
        if self.gpaths and self.gpaths_server:
            raw = subprocess.Popen(['ssh', self.gpaths_server, 'cat', self.gpaths],
                    stdout=subprocess.PIPE).stdout.read()
            paths = eval(raw) if raw else {}
            paths.update(self.paths)
            rem = [x for x in paths if self.version not in x]
            for x in rem:
                paths.pop(x)
            raw = ['%r : %r,'%(k, v) for k, v in paths.items()]
            raw = '{\n\n%s\n\n}\n'%('\n'.join(raw))
            with NamedTemporaryFile() as t:
                t.write(raw)
                t.flush()
                check_call(['scp', t.name, '%s:%s'%(self.gpaths_server,
                    self.gpaths)])
        if self.old_files:
            self.br = self.login_to_google()
            self.delete_old_files()

    def login_to_google(self):
        self.info('Logging into Google')
        return login_to_google(self.username, self.gmail_password)

    def get_files_hosted_by_google_code(self):
        from lxml import html
        self.info('Getting existing files in google code:', self.gc_project)
        raw = urllib2.urlopen(self.files_list).read()
        root = html.fromstring(raw)
        ans = {}
        for a in root.xpath('//td[@class="vt id col_0"]/a[@href]'):
            ans[a.text.strip()] = a.get('href')
        return ans

    def get_old_files(self):
        ans = set()
        for fname in self.get_files_hosted_by_google_code():
            m = self.filename_pat.match(fname)
            if m is not None:
                ans.add(fname)
        return ans

    def delete_old_files(self):
        if not self.old_files:
            return
        self.info('Deleting old files from Google Code...')
        for fname in self.old_files:
            self.info('\tDeleting', fname)
            self.br.open(self.delete_url%fname)
            self.br.select_form(predicate=lambda x: 'delete.do' in x.action)
            self.br.form.find_control(name='delete')
            self.br.submit(name='delete')

    def encode_upload_request(self, fields, file_path):
        BOUNDARY = '----------Googlecode_boundary_reindeer_flotilla'

        body = []

        # Add the metadata about the upload first
        for key, value in fields:
            body.extend(
            ['--' + BOUNDARY,
            'Content-Disposition: form-data; name="%s"' % key,
            '',
            value,
            ])

        # Now add the file itself
        file_name = os.path.basename(file_path)
        with open(file_path, 'rb') as f:
            file_content = f.read()

        body.extend(
            ['--' + BOUNDARY,
            'Content-Disposition: form-data; name="filename"; filename="%s"'
            % file_name,
            # The upload server determines the mime-type, no need to set it.
            'Content-Type: application/octet-stream',
            '',
            file_content,
            ])

        # Finalize the form body
        body.extend(['--' + BOUNDARY + '--', ''])
        body = [x.encode('ascii') if isinstance(x, unicode) else x for x in
                body]

        return ('multipart/form-data; boundary=%s' % BOUNDARY,
                b'\r\n'.join(body))

    def upload(self, fname, desc, labels=[], retry=0):
        form_fields = [('summary', desc)]
        form_fields.extend([('label', l.strip()) for l in labels])

        content_type, body = self.encode_upload_request(form_fields, fname)
        upload_uri = '/files'
        auth_token = base64.b64encode('%s:%s'% (self.username, self.password))
        headers = {
            'Authorization': 'Basic %s' % auth_token,
            'User-Agent': 'googlecode.com uploader v1',
            'Content-Type': content_type,
            }

        with NamedTemporaryFile(delete=False) as f:
            f.write(body)

        try:
            body = ReadFileWithProgressReporting(f.name)
            server = httplib.HTTPSConnection(self.upload_host)
            server.request('POST', upload_uri, body, headers)
            resp = server.getresponse()
            server.close()
        finally:
            os.remove(f.name)

        if resp.status == 201:
            return resp.getheader('Location')

        print ('Failed to upload with code %d and reason: %s'%(resp.status,
                resp.reason))
        if retry < 1:
            print ('Retrying in 5 seconds....')
            time.sleep(5)
            return self.upload(fname, desc, labels=labels, retry=retry+1)
        raise Exception('Failed to upload '+fname)


# }}}

class SourceForge(Base):  # {{{

    # Note that you should manually ssh once to username,project@frs.sourceforge.net
    # on the staging server so that the host key is setup

    def __init__(self, files, project, version, username, replace=False):
        self.username, self.project, self.version = username, project, version
        self.base = '/home/frs/project/c/ca/'+project
        self.rdir = self.base + '/' + version
        self.files = files

    def __call__(self):
        for x in self.files:
            start = time.time()
            self.info('Uploading', x)
            for i in range(5):
                try:
                    check_call(['rsync', '-h', '-z', '--progress', '-e', 'ssh -x', x,
                    '%s,%s@frs.sourceforge.net:%s'%(self.username, self.project,
                        self.rdir+'/')])
                except KeyboardInterrupt:
                    raise SystemExit(1)
                except:
                    print ('\nUpload failed, trying again in 30 seconds')
                    time.sleep(30)
                else:
                    break
            print ('Uploaded in', int(time.time() - start), 'seconds\n\n')

# }}}

class GitHub(Base):  # {{{

    API = 'https://api.github.com/'

    def __init__(self, files, reponame, version, username, password, replace=False):
        self.files, self.reponame, self.version, self.username, self.password, self.replace = (
            files, reponame, version, username, password, replace)
        self.current_tag_name = 'v' + self.version
        import requests
        self.requests = s = requests.Session()
        s.auth = (self.username, self.password)
        s.headers.update({'Accept': 'application/vnd.github.v3+json'})

    def __call__(self):
        releases = self.releases()
        self.clean_older_releases(releases)
        release = self.create_release(releases)
        upload_url = release['upload_url'].partition('{')[0]
        existing_assets = self.existing_assets(release['id'])
        for path, desc in self.files.iteritems():
            self.info('')
            url = self.API + 'repos/%s/%s/releases/assets/{}' % (self.username, self.reponame)
            fname = os.path.basename(path)
            if fname in existing_assets:
                self.info('Deleting %s from GitHub with id: %s' % (fname, existing_assets[fname]))
                r = self.requests.delete(url.format(existing_assets[fname]))
                if r.status_code != 204:
                    self.fail(r, 'Failed to delete %s from GitHub' % fname)
            r = self.do_upload(upload_url, path, desc, fname)
            if r.status_code != 201:
                self.fail(r, 'Failed to upload file: %s' % fname)
            try:
                r = self.requests.patch(url.format(r.json()['id']),
                                data=json.dumps({'name':fname, 'label':desc}))
            except Exception:
                time.sleep(15)
                r = self.requests.patch(url.format(r.json()['id']),
                                data=json.dumps({'name':fname, 'label':desc}))
            if r.status_code != 200:
                self.fail(r, 'Failed to set label for %s' % fname)

    def clean_older_releases(self, releases):
        for release in releases:
            if release.get('assets', None) and release['tag_name'] != self.current_tag_name:
                self.info('\nDeleting old released installers from: %s' % release['tag_name'])
                for asset in release['assets']:
                    r = self.requests.delete(self.API + 'repos/%s/%s/releases/assets/%s' % (self.username, self.reponame, asset['id']))
                    if r.status_code != 204:
                        self.fail(r, 'Failed to delete obsolete asset: %s for release: %s' % (
                            asset['name'], release['tag_name']))

    def do_upload(self, url, path, desc, fname):
        mime_type = mimetypes.guess_type(fname)[0]
        self.info('Uploading to GitHub: %s (%s)' % (fname, mime_type))
        with ReadFileWithProgressReporting(path) as f:
            return self.requests.post(
                url, headers={'Content-Type': mime_type, 'Content-Length':str(f._total)}, params={'name':fname},
                data=f)

    def fail(self, r, msg):
        print (msg, ' Status Code: %s' % r.status_code, file=sys.stderr)
        print ("JSON from response:", file=sys.stderr)
        pprint(dict(r.json()), stream=sys.stderr)
        raise SystemExit(1)

    def already_exists(self, r):
        error_code = r.json().get('errors', [{}])[0].get('code', None)
        return error_code == 'already_exists'

    def existing_assets(self, release_id):
        url = self.API + 'repos/%s/%s/releases/%s/assets' % (self.username, self.reponame, release_id)
        r = self.requests.get(url)
        if r.status_code != 200:
            self.fail('Failed to get assets for release')
        return {asset['name']:asset['id'] for asset in r.json()}

    def releases(self):
        url = self.API + 'repos/%s/%s/releases' % (self.username, self.reponame)
        r = self.requests.get(url)
        if r.status_code != 200:
            self.fail(r, 'Failed to list releases')
        return r.json()

    def create_release(self, releases):
        ' Create a release on GitHub or if it already exists, return the existing release '
        for release in releases:
            # Check for existing release
            if release['tag_name'] == self.current_tag_name:
                return release
        url = self.API + 'repos/%s/%s/releases' % (self.username, self.reponame)
        r = self.requests.post(url, data=json.dumps({
            'tag_name': self.current_tag_name,
            'target_commitish': 'master',
            'name': 'version %s' % self.version,
            'body': 'Release version %s' % self.version,
            'draft': False, 'prerelease':False
        }))
        if r.status_code != 201:
            self.fail(r, 'Failed to create release for version: %s' % self.version)
        return r.json()

# }}}

def generate_index():  # {{{
    os.chdir('/srv/download')
    releases = set()
    for x in os.listdir('.'):
        if os.path.isdir(x) and '.' in x:
            releases.add(tuple((int(y) for y in x.split('.'))))
    rmap = OrderedDict()
    for rnum in sorted(releases, reverse=True):
        series = rnum[:2] if rnum[0] == 0 else rnum[:1]
        if series not in rmap:
            rmap[series] = []
        rmap[series].append(rnum)

    template = '''<!DOCTYPE html>\n<html lang="en"> <head> <meta charset="utf-8"> <title>{title}</title> <style type="text/css"> {style} </style> </head> <body> <h1>{title}</h1> <p>{msg}</p> {body} </body> </html> '''  # noqa
    style = '''
    body { font-family: sans-serif; background-color: #eee; }
    a { text-decoration: none; }
    a:visited { color: blue }
    a:hover { color: red }
    ul { list-style-type: none }
    li { padding-bottom: 1ex }
    dd li { text-indent: 0; margin: 0 }
    dd ul { padding: 0; margin: 0 }
    dt { font-weight: bold }
    dd { margin-bottom: 2ex }
    '''
    body = []
    for series in rmap:
        body.append('<li><a href="{0}.html" title="Releases in the {0}.x series">{0}.x</a>\xa0\xa0\xa0<span style="font-size:smaller">[{1} releases]</span></li>'.format(  # noqa
                '.'.join(map(type(''), series)), len(rmap[series])))
    body = '<ul>{0}</ul>'.format(' '.join(body))
    index = template.format(title='Previous calibre releases', style=style, msg='Choose a series of calibre releases', body=body)
    with open('index.html', 'wb') as f:
        f.write(index.encode('utf-8'))

    for series, releases in rmap.iteritems():
        sname = '.'.join(map(type(''), series))
        body = [
            '<li><a href="{0}/" title="Release {0}">{0}</a></li>'.format('.'.join(map(type(''), r)))
            for r in releases]
        body = '<ul class="release-list">{0}</ul>'.format(' '.join(body))
        index = template.format(title='Previous calibre releases (%s.x)' % sname, style=style,
                                msg='Choose a calibre release', body=body)
        with open('%s.html' % sname, 'wb') as f:
            f.write(index.encode('utf-8'))

        for r in releases:
            rname = '.'.join(map(type(''), r))
            os.chdir(rname)
            try:
                body = []
                files = os.listdir('.')
                windows = [x for x in files if x.endswith('.msi')]
                if windows:
                    windows = ['<li><a href="{0}" title="{1}">{1}</a></li>'.format(
                        x, 'Windows 64-bit Installer' if '64bit' in x else 'Windows 32-bit Installer')
                        for x in windows]
                    body.append('<dt>Windows</dt><dd><ul>{0}</ul></dd>'.format(' '.join(windows)))
                portable = [x for x in files if '-portable-' in x]
                if portable:
                    body.append('<dt>Calibre Portable</dt><dd><a href="{0}" title="{1}">{1}</a></dd>'.format(
                        portable[0], 'Calibre Portable Installer'))
                osx = [x for x in files if x.endswith('.dmg')]
                if osx:
                    body.append('<dt>Apple Mac</dt><dd><a href="{0}" title="{1}">{1}</a></dd>'.format(
                        osx[0], 'OS X Disk Image (.dmg)'))
                linux = [x for x in files if x.endswith('.txz') or x.endswith('tar.bz2')]
                if linux:
                    linux = ['<li><a href="{0}" title="{1}">{1}</a></li>'.format(
                        x, 'Linux 64-bit binary' if 'x86_64' in x else 'Linux 32-bit binary')
                        for x in linux]
                    body.append('<dt>Linux</dt><dd><ul>{0}</ul></dd>'.format(' '.join(linux)))
                source = [x for x in files if x.endswith('.xz') or x.endswith('.gz')]
                if source:
                    body.append('<dt>Source Code</dt><dd><a href="{0}" title="{1}">{1}</a></dd>'.format(
                        source[0], 'Source code (all platforms)'))

                body = '<dl>{0}</dl>'.format(''.join(body))
                index = template.format(title='calibre release (%s)' % rname, style=style,
                                msg='', body=body)
                with open('index.html', 'wb') as f:
                    f.write(index.encode('utf-8'))
            finally:
                os.chdir('..')

# }}}

SERVER_BASE = '/srv/download/'

def upload_to_servers(files, version):  # {{{
    base = SERVER_BASE
    dest = os.path.join(base, version)
    if not os.path.exists(dest):
        os.mkdir(dest)
    for src in files:
        shutil.copyfile(src, os.path.join(dest, os.path.basename(src)))
    cwd = os.getcwd()
    try:
        generate_index()
    finally:
        os.chdir(cwd)

    for server, rdir in {'files':'/srv/download/'}.iteritems():
        print('Uploading to server:', server)
        server = '%s.calibre-ebook.com' % server
        # Copy the generated index files
        print ('Copying generated index')
        check_call(['rsync', '-hza', '-e', 'ssh -x', '--include', '*.html',
                    '--filter', '-! */', base, 'root@%s:%s' % (server, rdir)])
        # Copy the release files
        rdir = '%s%s/' % (rdir, version)
        for x in files:
            start = time.time()
            print ('Uploading', x)
            for i in range(5):
                try:
                    check_call(['rsync', '-h', '-z', '--progress', '-e', 'ssh -x', x,
                    'root@%s:%s'%(server, rdir)])
                except KeyboardInterrupt:
                    raise SystemExit(1)
                except:
                    print ('\nUpload failed, trying again in 30 seconds')
                    time.sleep(30)
                else:
                    break
            print ('Uploaded in', int(time.time() - start), 'seconds\n\n')

# }}}

def upload_to_dbs(files, version):  # {{{
    print('Uploading to fosshub.com')
    sys.stdout.flush()
    server = 'mirror10.fosshub.com'
    rdir = 'release/'
    def run_ssh(command, func=check_call):
        cmd = ['ssh', '-x', 'kovid@%s' % server, command]
        try:
            return func(cmd)
        except CalledProcessError as err:
            # fosshub is being a little flaky sshing into it is failing the first
            # time, needing a retry
            if err.returncode != 255:
                raise
            return func(cmd)

    old_files = set(run_ssh('ls ' + rdir, func=check_output).decode('utf-8').split())
    if len(files) < 7:
        existing = set(map(os.path.basename, files))
        # fosshub does not support partial re-uploads
        for f in glob.glob('%s/%s/calibre-*' % (SERVER_BASE, version)):
            if os.path.basename(f) not in existing:
                files[f] = None

    for x in files:
        start = time.time()
        print ('Uploading', x)
        sys.stdout.flush()
        old_files.discard(os.path.basename(x))
        for i in range(5):
            try:
                check_call(['rsync', '-h', '-z', '--progress', '-e', 'ssh -x', x,
                'kovid@%s:%s'%(server, rdir)])
            except KeyboardInterrupt:
                raise SystemExit(1)
            except:
                print ('\nUpload failed, trying again in 30 seconds')
                sys.stdout.flush()
                time.sleep(30)
            else:
                break
        print ('Uploaded in', int(time.time() - start), 'seconds\n\n')
        sys.stdout.flush()

    if old_files:
        run_ssh('rm -f %s' % (' '.join(rdir + x for x in old_files)))
    run_ssh('/home/kovid/uploadFiles')
# }}}

# CLI {{{
def cli_parser():
    epilog='Copyright Kovid Goyal 2012'

    p = ArgumentParser(
            description='Upload project files to a hosting service automatically',
            epilog=epilog
            )
    a = p.add_argument
    a('appname', help='The name of the application, all files to'
            ' upload should begin with this name')
    a('version', help='The version of the application, all files to'
            ' upload should contain this version')
    a('file_map', type=FileType('rb'),
            help='A file containing a mapping of files to be uploaded to '
            'descriptions of the files. The descriptions will be visible '
            'to users trying to get the file from the hosting service. '
            'The format of the file is filename: description, with one per '
            'line. filename can be a path to the file relative to the current '
            'directory.')
    a('--replace', action='store_true', default=False,
            help='If specified, existing files are replaced, otherwise '
            'they are skipped.')

    subparsers = p.add_subparsers(help='Where to upload to', dest='service',
            title='Service', description='Hosting service to upload to')
    gc = subparsers.add_parser('googlecode', help='Upload to googlecode',
            epilog=epilog)
    sf = subparsers.add_parser('sourceforge', help='Upload to sourceforge',
            epilog=epilog)
    gh = subparsers.add_parser('github', help='Upload to GitHub',
            epilog=epilog)
    cron = subparsers.add_parser('cron', help='Call script from cron')
    subparsers.add_parser('calibre', help='Upload to calibre file servers')
    subparsers.add_parser('dbs', help='Upload to fosshub.com')

    a = gc.add_argument

    a('project',
            help='The name of the project on google code we are uploading to')
    a('username',
            help='Username to log into your google account')
    a('password',
            help='Password to log into your google account')
    a('gc_password',
            help='Password for google code hosting.'
            ' Get it from http://code.google.com/hosting/settings')

    a('--path-map-server',
            help='A server to which the mapping of filenames to googlecode '
            'URLs will be uploaded. The upload happens via ssh, so you must '
            'have a working ssh agent')
    a('--path-map-location',
            help='Path on the server where the path map is placed.')

    a = sf.add_argument
    a('project',
            help='The name of the project on sourceforge we are uploading to')
    a('username',
            help='Sourceforge username')

    a = cron.add_argument
    a('username',
            help='Username to log into your google account')
    a('password',
            help='Password to log into your google account')

    a = gh.add_argument
    a('project',
            help='The name of the repository on GitHub we are uploading to')
    a('username',
            help='Username to log into your GitHub account')
    a('password',
            help='Password to log into your GitHub account')

    return p

def main(args=None):
    cli = cli_parser()
    args = cli.parse_args(args)
    files = {}
    if args.service != 'cron':
        with args.file_map as f:
            for line in f:
                fname, _, desc = line.partition(':')
                fname, desc = fname.strip(), desc.strip()
                if fname and desc:
                    files[fname] = desc

    ofiles = OrderedDict()
    for x in sorted(files, key=lambda x:os.stat(x).st_size, reverse=True):
        ofiles[x] = files[x]

    if args.service == 'googlecode':
        gc = GoogleCode(ofiles, args.appname, args.version, args.username,
                args.gc_password, args.password, args.project,
                gpaths_server=args.path_map_server,
                gpaths=args.path_map_location, reupload=args.replace)
        gc()
    elif args.service == 'sourceforge':
        sf = SourceForge(ofiles, args.project, args.version, args.username,
                replace=args.replace)
        sf()
    elif args.service == 'github':
        gh = GitHub(ofiles, args.project, args.version, args.username, args.password,
                replace=args.replace)
        gh()
    elif args.service == 'cron':
        login_to_google(args.username, args.password)
    elif args.service == 'calibre':
        upload_to_servers(ofiles, args.version)
    elif args.service == 'dbs':
        upload_to_dbs(ofiles, args.version)

if __name__ == '__main__':
    main()
# }}}
