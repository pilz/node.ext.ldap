from bda.ldap import LDAPProps
from bda.ldap.users import LDAPUsersConfig
from bda.ldap.users import LDAPGroupsConfig
from bda.ldap import SUBTREE

# === the new stuff ============

import os
import shutil
import subprocess
import tempfile
import time

from plone.testing import Layer
from pkg_resources import resource_filename

user = 'cn=Manager,dc=my-domain,dc=com'
pwd = 'secret'
props = LDAPProps('127.0.0.1', 12345, user, pwd, cache=False)
ucfg = LDAPUsersConfig(
        baseDN='dc=my-domain,dc=com',
        attrmap={
            'id': 'sn',
            'login': 'description',
            'telephoneNumber': 'telephoneNumber',
            'sn': 'sn',
            },
        scope=SUBTREE,
        queryFilter='(objectClass=person)',
        )

#gcfg_openldap = LDAPGroupsConfig(
#        baseDN='dc=my-domain,dc=com',
#        id_attr='cn',
#        scope=SUBTREE,
#        queryFilter='(objectClass=groupOfNames)',
#        member_relation='member:dn',
#        )


def resource(string):
    return resource_filename(__name__, 'tests/'+string)


SCHEMA = os.environ.get('SCHEMA')
try:
    SLAPDBIN = os.environ['SLAPD_BIN']
    SLAPDURIS = os.environ['SLAPD_URIS']
    LDAPADDBIN = os.environ['LDAP_ADD_BIN']
    LDAPDELETEBIN = os.environ['LDAP_DELETE_BIN']
except KeyError:
    raise RuntimeError("Environment variables SLAPD_BIN,"
            " SLAPD_URIS, LDAP_ADD_BIN, LDAP_DELETE_BIN needed.")


slapdconf_template = """\
%(schema)s

pidfile		%(confdir)s/slapd.pid
argsfile	%(confdir)s/slapd.args

database	bdb
suffix		"dc=my-domain,dc=com"
rootdn		"%(binddn)s"
rootpw		%(bindpw)s
directory	%(dbdir)s
# Indices to maintain
index	objectClass	eq
"""

class SlapdConf(Layer):
    """generate slapd.conf
    """
    def __init__(self, schema):
        """
        ``schema``: List of paths to our schema files
        """
        super(SlapdConf, self).__init__()
        self.schema = schema

    def setUp(self):
        """take a template, replace, write slapd.conf store path for others to
        knows
        """
        binddn = self['binddn'] = "cn=Manager,dc=my-domain,dc=com"
        bindpw = self['bindpw'] = "secret"
        confdir = self['confdir'] = tempfile.mkdtemp()
        dbdir = self['dbdir'] = "%s/openldap-data" % (confdir,)
        slapdconf = self['slapdconf'] = "%s/slapd.conf" % (confdir,)
        schema = '\n'.join(
                ["include %s" % (schema,) for schema in self.schema]
                )
        # generate config file
        with open(slapdconf, 'w') as slapdconf:
            slapdconf.write(slapdconf_template % dict(
                binddn=binddn,
                bindpw=bindpw,
                confdir=confdir,
                dbdir=dbdir,
                schema=schema
                ))
        os.mkdir(dbdir)
        print "SlapdConf set up."

    def tearDown(self):
        """remove our traces
        """
        shutil.rmtree(self['confdir'])
        print "SlapdConf torn down."

schema = (
        resource('schema/core.schema'),
        resource('schema/cosine.schema'),
        resource('schema/inetorgperson.schema'),
        )
SLAPD_CONF = SlapdConf(schema)


class LDAPLayer(Layer):
    """Base class for ldap layers to _subclass_ from
    """
    defaultBases = (SLAPD_CONF,)

    def __init__(self, uris=SLAPDURIS, **kws):
        super(LDAPLayer, self).__init__(**kws)
        self['uris'] = uris


class Slapd(LDAPLayer):
    """Start/Stop an LDAP Server
    """
    def __init__(self, slapdbin=SLAPDBIN, **kws):
        super(Slapd, self).__init__(**kws)
        self.slapdbin = slapdbin

    def setUp(self):
        """start slapd
        """
        print "\nStarting LDAP server: ",
        cmd = [self.slapdbin, '-f', self['slapdconf'], '-h', self['uris'],
                '-d', '0']
        self.slapd = subprocess.Popen(cmd)
        time.sleep(1)
        print "done."

    def tearDown(self):
        """stop the previously started slapd
        """
        print "\nStopping LDAP Server: ",
        os.kill(self.slapd.pid, 15)
        print "waiting for slapd to terminate...",
        self.slapd.wait()
        print "done."
        print "Whiping ldap data directory %s: " % (self['dbdir'],),
        for file in os.listdir(self['dbdir']):
            os.remove('%s/%s' % (self['dbdir'], file))
        print "done."

SLAPD = Slapd()


class Ldif(LDAPLayer):
    """Adds/removes ldif data to/from a server
    """
    defaultBases = (SLAPD,)

    def __init__(self,
            ldifs=tuple(),
            ldapaddbin=LDAPADDBIN,
            ldapdeletebin=LDAPDELETEBIN,
            **kws):
        super(Ldif, self).__init__(**kws)
        self.ldapaddbin = ldapaddbin
        self.ldapdeletebin = ldapdeletebin
        self.ldifs = type(ldifs) is tuple and ldifs or (ldifs,)

    def setUp(self):
        """run ldapadd for list of ldifs
        """
        print
        for ldif in self.ldifs:
            print "Adding ldif %s: " % (ldif,),
            cmd = [self.ldapaddbin, '-f', ldif, '-x', '-D', self['binddn'], '-w',
                    self['bindpw'], '-c', '-a', '-H', self['uris']]
            retcode = subprocess.call(cmd)
            print "done."

    def tearDown(self):
        """remove previously added ldifs
        """
        print
        for ldif in self.ldifs:
            print "Removing ldif %s recursively: " % (ldif,),
            with open(ldif) as ldif:
                dns = [x.strip().split(' ',1)[1]  for x in ldif if
                        x.startswith('dn: ')]
            cmd = [self.ldapdeletebin, '-x', '-D', self['binddn'], '-c', '-r',
                    '-w', self['bindpw'], '-H', self['uris']] + dns
            retcode = subprocess.call(cmd, stderr=subprocess.PIPE)
            print "done."


# old ones used by current bda.ldap tests - 2010-11-09
LDIF_data = Ldif(
        resource('ldifs/data.ldif'),
        name='LDIF_data',
        )
LDIF_principals = Ldif(
        resource('ldifs/principals.ldif'),
        bases=(LDIF_data,),
        name='LDIF_principals',
        )

# new ones
LDIF_base = Ldif(resource('ldifs/base.ldif'))
LDIF_users300 = Ldif(
        resource('ldifs/users300.ldif'),
        bases=(LDIF_base,),
        name="LDIF_users300",
        )
LDIF_users700 = Ldif(
        resource('ldifs/users700.ldif'),
        bases=(LDIF_base,),
        name="LDIF_users700",
        )
LDIF_users1000 = Ldif(
        resource('ldifs/users1000.ldif'),
        bases=(LDIF_base,),
        name="LDIF_users1000",
        )
LDIF_users2000 = Ldif(
        resource('ldifs/users2000.ldif'),
        bases=(LDIF_base,),
        name="LDIF_users2000",
        )
