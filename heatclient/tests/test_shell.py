# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or
# implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import fixtures
import os
from oslotest import mockpatch
import re
import six
from six.moves.urllib import parse
from six.moves.urllib import request
import sys
import tempfile
import testscenarios
import testtools
import uuid

from oslo.serialization import jsonutils
from oslo.utils import encodeutils
from requests_mock.contrib import fixture as rm_fixture

from keystoneclient import fixture as keystone_fixture

from mox3 import mox

from heatclient.common import utils
from heatclient import exc
import heatclient.shell
from heatclient.tests import fakes

load_tests = testscenarios.load_tests_apply_scenarios
TEST_VAR_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__),
                                            'var'))

BASE_HOST = 'http://keystone.example.com'
BASE_URL = "%s:5000/" % BASE_HOST
V2_URL = "%sv2.0" % BASE_URL
V3_URL = "%sv3" % BASE_URL
HEAT_URL = 'http://heat.example.com'


FAKE_ENV_KEYSTONE_V2 = {
    'OS_USERNAME': 'username',
    'OS_PASSWORD': 'password',
    'OS_TENANT_NAME': 'tenant_name',
    'OS_AUTH_URL': BASE_URL,
}

FAKE_ENV_KEYSTONE_V3 = {
    'OS_USERNAME': 'username',
    'OS_PASSWORD': 'password',
    'OS_TENANT_NAME': 'tenant_name',
    'OS_AUTH_URL': BASE_URL,
    'OS_USER_DOMAIN_ID': 'default',
    'OS_PROJECT_DOMAIN_ID': 'default',
}


class TestCase(testtools.TestCase):

    tokenid = uuid.uuid4().hex

    def setUp(self):
        super(TestCase, self).setUp()
        self.requests = self.useFixture(rm_fixture.Fixture())

    def set_fake_env(self, fake_env):
        client_env = ('OS_USERNAME', 'OS_PASSWORD', 'OS_TENANT_ID',
                      'OS_TENANT_NAME', 'OS_AUTH_URL', 'OS_REGION_NAME',
                      'OS_AUTH_TOKEN', 'OS_NO_CLIENT_AUTH', 'OS_SERVICE_TYPE',
                      'OS_ENDPOINT_TYPE', 'HEAT_URL')

        for key in client_env:
            self.useFixture(
                fixtures.EnvironmentVariable(key, fake_env.get(key)))

    # required for testing with Python 2.6
    def assertRegexpMatches(self, text, expected_regexp, msg=None):
        """Fail the test unless the text matches the regular expression."""
        if isinstance(expected_regexp, six.string_types):
            expected_regexp = re.compile(expected_regexp)
        if not expected_regexp.search(text):
            msg = msg or "Regexp didn't match"
            msg = '%s: %r not found in %r' % (
                msg, expected_regexp.pattern, text)
            raise self.failureException(msg)

    # required for testing with Python 2.6
    def assertNotRegexpMatches(self, text, expected_regexp, msg=None):
        try:
            self.assertRegexpMatches(text, expected_regexp, msg)
        except self.failureException:
            pass
        else:
            raise self.failureException(msg)

    def shell_error(self, argstr, error_match):
        orig = sys.stderr
        sys.stderr = six.StringIO()
        _shell = heatclient.shell.HeatShell()
        e = self.assertRaises(Exception, _shell.main, argstr.split())
        self.assertRegexpMatches(e.__str__(), error_match)
        err = sys.stderr.getvalue()
        sys.stderr.close()
        sys.stderr = orig
        return err

    def script_heat_list(self, url=None, **kwargs):
        if not url:
            url = '/stacks?'

        return fakes.script_heat_list(self.requests, url, **kwargs)

    def script_heat_error(self, **kwargs):
        self.requests.get('/stacks/bad', status_code=400, **kwargs)

    def register_keystone_v2_token_fixture(self):
        v2_token = keystone_fixture.V2Token(token_id=self.tokenid)
        service = v2_token.add_service('orchestration')
        service.add_endpoint(HEAT_URL, region='RegionOne')
        self.requests.post('%s/tokens' % V2_URL, json=v2_token)

    def register_keystone_v3_token_fixture(self):
        v3_token = keystone_fixture.V3Token()
        service = v3_token.add_service('orchestration')
        service.add_standard_endpoints(public=HEAT_URL)
        self.requests.post('%s/auth/tokens' % V3_URL,
                           json=v3_token,
                           headers={'X-Subject-Token': self.tokenid})

    def register_keystone_auth_fixture(self):
        self.register_keystone_v2_token_fixture()
        self.register_keystone_v3_token_fixture()

        version_list = keystone_fixture.DiscoveryList(href=BASE_URL)
        self.requests.get(BASE_URL, json=version_list)

    # NOTE(tlashchova): this overrides the testtools.TestCase.patch method
    # that does simple monkey-patching in favor of mock's patching
    def patch(self, target, **kwargs):
        mockfixture = self.useFixture(mockpatch.Patch(target, **kwargs))
        return mockfixture.mock

    def assertJsonEqual(self, json_data, req):
        self.assertEqual(json_data, jsonutils.loads(req.body))


class EnvVarTest(TestCase):

    scenarios = [
        ('username', dict(
            remove='OS_USERNAME',
            err='You must provide a username')),
        ('password', dict(
            remove='OS_PASSWORD',
            err='You must provide a password')),
        ('tenant_name', dict(
            remove='OS_TENANT_NAME',
            err='You must provide a tenant id')),
        ('auth_url', dict(
            remove='OS_AUTH_URL',
            err='You must provide an auth url')),
    ]

    def test_missing_auth(self):

        fake_env = {
            'OS_USERNAME': 'username',
            'OS_PASSWORD': 'password',
            'OS_TENANT_NAME': 'tenant_name',
            'OS_AUTH_URL': 'http://no.where',
        }
        fake_env[self.remove] = None
        self.set_fake_env(fake_env)
        self.shell_error('stack-list', self.err)


class EnvVarTestToken(TestCase):

    scenarios = [
        ('tenant_id', dict(
            remove='OS_TENANT_ID',
            err='You must provide a tenant id')),
        ('auth_url', dict(
            remove='OS_AUTH_URL',
            err='You must provide an auth url')),
    ]

    def test_missing_auth(self):

        fake_env = {
            'OS_AUTH_TOKEN': 'atoken',
            'OS_TENANT_ID': 'tenant_id',
            'OS_AUTH_URL': 'http://no.where',
        }
        fake_env[self.remove] = None
        self.set_fake_env(fake_env)
        self.shell_error('stack-list', self.err)


class ShellParamValidationTest(TestCase):

    scenarios = [
        ('create', dict(
            command='create ts -P "a!b"',
            err='Malformed parameter')),
        ('stack-create', dict(
            command='stack-create ts -P "ab"',
            err='Malformed parameter')),
        ('update', dict(
            command='update ts -P "a~b"',
            err='Malformed parameter')),
        ('stack-update', dict(
            command='stack-update ts -P "a-b"',
            err='Malformed parameter')),
    ]


    def test_bad_parameters(self):
        self.register_keystone_auth_fixture()
        fake_env = {
            'OS_USERNAME': 'username',
            'OS_PASSWORD': 'password',
            'OS_TENANT_NAME': 'tenant_name',
            'OS_AUTH_URL': BASE_URL,
        }
        self.set_fake_env(fake_env)
        template_file = os.path.join(TEST_VAR_DIR, 'minimal.template')
        cmd = '%s --template-file=%s ' % (self.command, template_file)
        self.shell_error(cmd, self.err)


class ShellValidationTest(TestCase):

    def test_failed_auth(self):
        self.register_keystone_auth_fixture()
        failed_msg = 'Unable to authenticate user with credentials provided'
        self.requests.get('%s/stacks?' % HEAT_URL,
                          text=raise_exc_cb(exc.Unauthorized(failed_msg)))
        self.set_fake_env(FAKE_ENV_KEYSTONE_V2)
        self.shell_error('stack-list', failed_msg)

    def test_stack_create_validation(self):
        self.register_keystone_auth_fixture()
        self.set_fake_env(FAKE_ENV_KEYSTONE_V2)
        self.shell_error(
            'stack-create teststack '
            '--parameters="InstanceType=m1.large;DBUsername=wp;'
            'DBPassword=verybadpassword;KeyName=heat_key;'
            'LinuxDistribution=F17"',
            'Need to specify exactly one of')

    def test_stack_create_validation_keystone_v3(self):
        self.register_keystone_auth_fixture()
        self.set_fake_env(FAKE_ENV_KEYSTONE_V3)
        self.shell_error(
            'stack-create teststack '
            '--parameters="InstanceType=m1.large;DBUsername=wp;'
            'DBPassword=verybadpassword;KeyName=heat_key;'
            'LinuxDistribution=F17"',
            'Need to specify exactly one of')


class ShellBase(TestCase):

    def setUp(self):
        super(ShellBase, self).setUp()
        self.m = mox.Mox()
        self.addCleanup(self.m.VerifyAll)
        self.addCleanup(self.m.UnsetStubs)

        # Some tests set exc.verbose = 1, so reset on cleanup
        def unset_exc_verbose():
            exc.verbose = 0

        self.addCleanup(unset_exc_verbose)

    def shell(self, argstr):
        orig = sys.stdout
        try:
            sys.stdout = six.StringIO()
            _shell = heatclient.shell.HeatShell()
            _shell.main(argstr.split())
            self.subcommands = _shell.subcommands.keys()
        except SystemExit:
            exc_type, exc_value, exc_traceback = sys.exc_info()
            self.assertEqual(0, exc_value.code)
        finally:
            out = sys.stdout.getvalue()
            sys.stdout.close()
            sys.stdout = orig

        return out


class ShellTestNoMox(TestCase):
    # NOTE(dhu):  This class is reserved for no Mox usage.  Instead,
    # use requests_mock to expose errors from json_request.
    def setUp(self):
        super(ShellTestNoMox, self).setUp()
        self.set_fake_env(FAKE_ENV_KEYSTONE_V2)

    def shell(self, argstr):
        orig = sys.stdout
        try:
            sys.stdout = six.StringIO()
            _shell = heatclient.shell.HeatShell()
            _shell.main(argstr.split())
            self.subcommands = _shell.subcommands.keys()
        except SystemExit:
            exc_type, exc_value, exc_traceback = sys.exc_info()
            self.assertEqual(0, exc_value.code)
        finally:
            out = sys.stdout.getvalue()
            sys.stdout.close()
            sys.stdout = orig

        return out

    # This function tests err msg handling
    def test_stack_create_parameter_missing_err_msg(self):
        self.register_keystone_auth_fixture()

        resp_dict = {"error":
                     {"message": 'The Parameter (key_name) was not provided.',
                      "type": "UserParameterMissing"}}

        self.requests.post('http://heat.example.com/stacks',
                           status_code=400,
                           headers={'Content-Type': 'application/json'},
                           json=resp_dict)

        template_file = os.path.join(TEST_VAR_DIR, 'minimal.template')

        self.shell_error('stack-create -f %s stack' % template_file,
                         'The Parameter \(key_name\) was not provided.')

    def test_event_list(self):
        eventid1 = uuid.uuid4().hex
        eventid2 = uuid.uuid4().hex
        self.register_keystone_auth_fixture()

        h = {'Content-Type': 'text/plain; charset=UTF-8',
             'location': 'http://heat.example.com/stacks/myStack/60f83b5e'}
        self.requests.get('http://heat.example.com/stacks/myStack',
                          status_code=302,
                          headers=h)

        resp_dict = {"events": [
                     {"event_time": "2014-12-05T14:14:30Z",
                      "id": eventid1,
                      "links": [{"href": "http://heat.example.com:8004/foo",
                                 "rel": "self"},
                                {"href": "http://heat.example.com:8004/foo2",
                                 "rel": "resource"},
                                {"href": "http://heat.example.com:8004/foo3",
                                 "rel": "stack"}],
                      "logical_resource_id": "myDeployment",
                      "physical_resource_id": None,
                      "resource_name": "myDeployment",
                      "resource_status": "CREATE_IN_PROGRESS",
                      "resource_status_reason": "state changed"},
                     {"event_time": "2014-12-05T14:14:30Z",
                      "id": eventid2,
                      "links": [{"href": "http://heat.example.com:8004/foo",
                                 "rel": "self"},
                                {"href": "http://heat.example.com:8004/foo2",
                                 "rel": "resource"},
                                {"href": "http://heat.example.com:8004/foo3",
                                 "rel": "stack"}],
                      "logical_resource_id": "myDeployment",
                      "physical_resource_id": uuid.uuid4().hex,
                      "resource_name": "myDeployment",
                      "resource_status": "CREATE_COMPLETE",
                      "resource_status_reason": "state changed"}]}

        self.requests.get('http://heat.example.com/stacks/myStack%2F60f83b5e/'
                          'resources/myDeployment/events',
                          headers={'Content-Type': 'application/json'},
                          json=resp_dict)

        list_text = self.shell('event-list -r myDeployment myStack')

        required = [
            'resource_name',
            'id',
            'resource_status_reason',
            'resource_status',
            'event_time',
            'myDeployment',
            eventid1,
            eventid2,
            'state changed',
            'CREATE_IN_PROGRESS',
            '2014-12-05T14:14:30Z',
            '2014-12-05T14:14:30Z',
        ]

        for r in required:
            self.assertRegexpMatches(list_text, r)


class ShellTestNoMoxV3(ShellTestNoMox):

    def _set_fake_env(self):
        self.set_fake_env(FAKE_ENV_KEYSTONE_V3)


def raise_exc_cb(e):
    def _cb(request, context):
        raise e

    return _cb


class ShellTestCommon(ShellBase):

    def setUp(self):
        super(ShellTestCommon, self).setUp()
        self.set_fake_env(FAKE_ENV_KEYSTONE_V2)

    def test_help_unknown_command(self):
        self.assertRaises(exc.CommandError, self.shell, 'help foofoo')

    def test_help(self):
        required = [
            '^usage: heat',
            '(?m)^See "heat help COMMAND" for help on a specific command',
        ]
        for argstr in ['--help', 'help']:
            help_text = self.shell(argstr)
            for r in required:
                self.assertRegexpMatches(help_text, r)

    def test_command_help(self):
        output = self.shell('help help')
        self.assertIn('usage: heat help [<subcommand>]', output)
        subcommands = list(self.subcommands)
        for command in subcommands:
            if command.replace('_', '-') == 'bash-completion':
                continue
            output1 = self.shell('help %s' % command)
            output2 = self.shell('%s --help' % command)
            self.assertEqual(output1, output2)
            self.assertRegexpMatches(output1, '^usage: heat %s' % command)

    def test_debug_switch_raises_error(self):
        self.register_keystone_auth_fixture()
        self.requests.get('%s/stacks?' % HEAT_URL,
                          text=raise_exc_cb(exc.Unauthorized("FAIL")))

        args = ['--debug', 'stack-list']
        self.assertRaises(exc.Unauthorized, heatclient.shell.main, args)

    def test_dash_d_switch_raises_error(self):
        self.register_keystone_auth_fixture()
        self.requests.get('%s/stacks?' % HEAT_URL,
                          text=raise_exc_cb(exc.CommandError("FAIL")))

        args = ['-d', 'stack-list']
        self.assertRaises(exc.CommandError, heatclient.shell.main, args)

    def test_no_debug_switch_no_raises_errors(self):
        self.register_keystone_auth_fixture()
        self.requests.get('%s/stacks?' % HEAT_URL,
                          text=raise_exc_cb(exc.Unauthorized("FAIL")))

        args = ['stack-list']
        self.assertRaises(SystemExit, heatclient.shell.main, args)

    def test_help_on_subcommand(self):
        required = [
            '^usage: heat stack-list',
            "(?m)^List the user's stacks",
        ]
        argstrings = [
            'help stack-list',
        ]
        for argstr in argstrings:
            help_text = self.shell(argstr)
            for r in required:
                self.assertRegexpMatches(help_text, r)


class ShellTestUserPass(ShellBase):

    def setUp(self):
        super(ShellTestUserPass, self).setUp()
        self._set_fake_env()

    def _set_fake_env(self):
        self.set_fake_env(FAKE_ENV_KEYSTONE_V2)

    def test_stack_list(self):
        self.register_keystone_auth_fixture()
        self.script_heat_list()

        list_text = self.shell('stack-list')

        required = [
            'id',
            'stack_status',
            'creation_time',
            'teststack',
            '1',
            'CREATE_COMPLETE',
            'IN_PROGRESS',
        ]
        for r in required:
            self.assertRegexpMatches(list_text, r)
        self.assertNotRegexpMatches(list_text, 'parent')

    def test_stack_list_show_nested(self):
        self.register_keystone_auth_fixture()
        expected_url = '/stacks?%s' % parse.urlencode({
            'show_nested': True,
        }, True)
        self.script_heat_list(expected_url, show_nested=True)

        list_text = self.shell('stack-list'
                               ' --show-nested')

        required = [
            'teststack',
            'teststack2',
            'teststack_nested',
            'parent',
            'theparentof3'
        ]
        for r in required:
            self.assertRegexpMatches(list_text, r)

    def test_stack_list_show_owner(self):
        self.register_keystone_auth_fixture()
        self.script_heat_list()

        list_text = self.shell('stack-list --show-owner')

        required = [
            'stack_owner',
            'testowner',
        ]
        for r in required:
            self.assertRegexpMatches(list_text, r)

    def test_parsable_error(self):
        self.register_keystone_auth_fixture()
        message = "The Stack (bad) could not be found."
        resp_dict = {
            "explanation": "The resource could not be found.",
            "code": 404,
            "error": {
                "message": message,
                "type": "StackNotFound",
                "traceback": "",
            },
            "title": "Not Found"
        }

        self.script_heat_error(json=resp_dict)

        e = self.assertRaises(exc.HTTPException, self.shell, "stack-show bad")
        self.assertEqual("ERROR: " + message, str(e))

    def test_parsable_verbose(self):
        self.register_keystone_auth_fixture()
        message = "The Stack (bad) could not be found."
        resp_dict = {
            "explanation": "The resource could not be found.",
            "code": 404,
            "error": {
                "message": message,
                "type": "StackNotFound",
                "traceback": "<TRACEBACK>",
            },
            "title": "Not Found"
        }

        self.script_heat_error(json=resp_dict)

        exc.verbose = 1

        e = self.assertRaises(exc.HTTPException, self.shell, "stack-show bad")
        self.assertIn(message, str(e))

    def test_parsable_malformed_error(self):
        self.register_keystone_auth_fixture()
        invalid_json = "ERROR: {Invalid JSON Error."
        self.script_heat_error(text=invalid_json)

        e = self.assertRaises(exc.HTTPException, self.shell, "stack-show bad")
        self.assertEqual("ERROR: " + invalid_json, str(e))

    def test_parsable_malformed_error_missing_message(self):
        self.register_keystone_auth_fixture()
        missing_message = {
            "explanation": "The resource could not be found.",
            "code": 404,
            "error": {
                "type": "StackNotFound",
                "traceback": "",
            },
            "title": "Not Found"
        }

        self.script_heat_error(json=missing_message)

        e = self.assertRaises(exc.HTTPException, self.shell, "stack-show bad")
        self.assertEqual("ERROR: Internal Error", str(e))

    def test_parsable_malformed_error_missing_traceback(self):
        self.register_keystone_auth_fixture()
        message = "The Stack (bad) could not be found."
        resp_dict = {
            "explanation": "The resource could not be found.",
            "code": 404,
            "error": {
                "message": message,
                "type": "StackNotFound",
            },
            "title": "Not Found"
        }

        self.script_heat_error(json=resp_dict)

        exc.verbose = 1

        e = self.assertRaises(exc.HTTPException, self.shell, "stack-show bad")
        self.assertEqual("ERROR: The Stack (bad) could not be found.\n",
                         str(e))

    def test_stack_show(self):
        self.register_keystone_auth_fixture()
        resp_dict = {"stack": {
            "id": "1",
            "stack_name": "teststack",
            "stack_status": 'CREATE_COMPLETE',
            "creation_time": "2012-10-25T01:58:47Z"
        }}
        self.requests.get('/stacks/teststack/1',
                          headers={'Content-Type': 'application/json'},
                          json=resp_dict)

        list_text = self.shell('stack-show teststack/1')

        required = [
            'id',
            'stack_name',
            'stack_status',
            'creation_time',
            'teststack',
            'CREATE_COMPLETE',
            '2012-10-25T01:58:47Z'
        ]
        for r in required:
            self.assertRegexpMatches(list_text, r)

    def test_stack_abandon(self):
        self.register_keystone_auth_fixture()

        resp_dict = {"stack": {
            "id": "1",
            "stack_name": "teststack",
            "stack_status": 'CREATE_COMPLETE',
            "creation_time": "2012-10-25T01:58:47Z"
        }}

        abandoned_stack = {
            "action": "CREATE",
            "status": "COMPLETE",
            "name": "teststack",
            "id": "1",
            "resources": {
                "foo": {
                    "name": "foo",
                    "resource_id": "test-res-id",
                    "action": "CREATE",
                    "status": "COMPLETE",
                    "resource_data": {},
                    "metadata": {},
                }
            }
        }

        self.requests.get('/stacks/teststack/1',
                          headers={'Content-Type': 'application/json'},
                          json=resp_dict)
        self.requests.delete('/stacks/teststack/1/abandon',
                             headers={'Content-Type': 'application/json'},
                             json=abandoned_stack)

        abandon_resp = self.shell('stack-abandon teststack/1')
        self.assertEqual(abandoned_stack, jsonutils.loads(abandon_resp))

    def test_stack_abandon_with_outputfile(self):
        self.register_keystone_auth_fixture()

        resp_dict = {"stack": {
            "id": "1",
            "stack_name": "teststack",
            "stack_status": 'CREATE_COMPLETE',
            "creation_time": "2012-10-25T01:58:47Z"
        }}

        abandoned_stack = {
            "action": "CREATE",
            "status": "COMPLETE",
            "name": "teststack",
            "id": "1",
            "resources": {
                "foo": {
                    "name": "foo",
                    "resource_id": "test-res-id",
                    "action": "CREATE",
                    "status": "COMPLETE",
                    "resource_data": {},
                    "metadata": {},
                }
            }
        }

        self.requests.get('/stacks/teststack/1',
                          headers={'Content-Type': 'application/json'},
                          json=resp_dict)
        self.requests.delete('/stacks/teststack/1/abandon',
                             headers={'Content-Type': 'application/json'},
                             json=abandoned_stack)

        with tempfile.NamedTemporaryFile() as file_obj:
            self.shell('stack-abandon teststack/1 -O %s' % file_obj.name)
            result = jsonutils.loads(file_obj.read().decode())
            self.assertEqual(abandoned_stack, result)

    def _output_fake_response(self):

        resp_dict = {"stack": {
            "id": "1",
            "stack_name": "teststack",
            "stack_status": 'CREATE_COMPLETE',
            "creation_time": "2012-10-25T01:58:47Z",
            "outputs": [
                {
                    "output_value": "value1",
                    "output_key": "output1",
                    "description": "test output 1",
                },
                {
                    "output_value": ["output", "value", "2"],
                    "output_key": "output2",
                    "description": "test output 2",
                },
                {
                    "output_value": u"test\u2665",
                    "output_key": "output_uni",
                    "description": "test output unicode",
                },
            ],
            "creation_time": "2012-10-25T01:58:47Z"
        }}

        self.requests.get('/stacks/teststack/1',
                          headers={'Content-Type': 'application/json'},
                          json=resp_dict)

    def _error_output_fake_response(self):

        resp_dict = {"stack": {
            "id": "1",
            "stack_name": "teststack",
            "stack_status": 'CREATE_COMPLETE',
            "creation_time": "2012-10-25T01:58:47Z",
            "outputs": [
                {
                    "output_value": "null",
                    "output_key": "output1",
                    "description": "test output 1",
                    "output_error": "The Referenced Attribute (0 PublicIP) "
                                    "is incorrect."
                },
            ],
            "creation_time": "2012-10-25T01:58:47Z"
        }}

        self.requests.get('/stacks/teststack/1',
                          headers={'Content-Type': 'application/json'},
                          json=resp_dict)

    def test_output_list(self):
        self.register_keystone_auth_fixture()
        self._output_fake_response()
        list_text = self.shell('output-list teststack/1')
        for r in ['output1', 'output2', 'output_uni']:
            self.assertRegexpMatches(list_text, r)

    def test_output_show(self):
        self.register_keystone_auth_fixture()
        self._output_fake_response()
        list_text = self.shell('output-show teststack/1 output1')
        self.assertRegexpMatches(list_text, 'value1')

    def test_output_show_unicode(self):
        self.register_keystone_auth_fixture()
        self._output_fake_response()
        list_text = self.shell('output-show teststack/1 output_uni')
        self.assertRegexpMatches(list_text, u'test\u2665')

    def test_output_show_error(self):
        self.register_keystone_auth_fixture()
        self._error_output_fake_response()
        error = self.assertRaises(
            exc.CommandError, self.shell,
            'output-show teststack/1 output1')
        self.assertIn('The Referenced Attribute (0 PublicIP) is incorrect.',
                      str(error))

    def test_template_show_cfn(self):
        self.register_keystone_auth_fixture()
        template_data = open(os.path.join(TEST_VAR_DIR,
                                          'minimal.template')).read()

        self.requests.get('/stacks/teststack/template',
                          headers={'Content-Type': 'application/json'},
                          text=template_data)

        show_text = self.shell('template-show teststack')
        required = [
            '{',
            '  "AWSTemplateFormatVersion": "2010-09-09"',
            '  "Outputs": {}',
            '  "Resources": {}',
            '  "Parameters": {}',
            '}'
        ]
        for r in required:
            self.assertRegexpMatches(show_text, r)

    def test_template_show_cfn_unicode(self):
        self.register_keystone_auth_fixture()
        resp_dict = {"AWSTemplateFormatVersion": "2010-09-09",
                     "Description": u"test\u2665",
                     "Outputs": {},
                     "Resources": {},
                     "Parameters": {}}

        self.requests.get('/stacks/teststack/template',
                          headers={'Content-Type': 'application/json'},
                          json=resp_dict)

        show_text = self.shell('template-show teststack')
        required = [
            '{',
            '  "AWSTemplateFormatVersion": "2010-09-09"',
            '  "Outputs": {}',
            '  "Parameters": {}',
            u'  "Description": "test\u2665"',
            '  "Resources": {}',
            '}'
        ]
        for r in required:
            self.assertRegexpMatches(show_text, r)

    def test_template_show_hot(self):
        self.register_keystone_auth_fixture()
        resp_dict = {"heat_template_version": "2013-05-23",
                     "parameters": {},
                     "resources": {},
                     "outputs": {}}

        self.requests.get('/stacks/teststack/template',
                          headers={'Content-Type': 'application/json'},
                          json=resp_dict)

        show_text = self.shell('template-show teststack')
        required = [
            "heat_template_version: '2013-05-23'",
            "outputs: {}",
            "parameters: {}",
            "resources: {}"
        ]
        for r in required:
            self.assertRegexpMatches(show_text, r)

    def _test_stack_preview(self, timeout=None, enable_rollback=False):
        self.register_keystone_auth_fixture()
        resp_dict = {"stack": {
            "id": "1",
            "stack_name": "teststack",
            "stack_status": 'CREATE_COMPLETE',
            "resources": {'1': {'name': 'r1'}},
            "creation_time": "2012-10-25T01:58:47Z",
            "timeout_mins": timeout,
            "disable_rollback": not(enable_rollback)
        }}

        location = 'http://no.where/v1/tenant_id/stacks/teststack2/2'

        self.requests.post('/stacks/preview',
                           request_headers={'X-Auth-Key': 'password',
                                            'X-Auth-User': 'username'},
                           headers={'location': location,
                                    'Content-Type': 'application/json'},
                           json=resp_dict)

        template_file = os.path.join(TEST_VAR_DIR, 'minimal.template')
        cmd = ('stack-preview teststack '
               '--template-file=%s '
               '--parameters="InstanceType=m1.large;DBUsername=wp;'
               'DBPassword=verybadpassword;KeyName=heat_key;'
               'LinuxDistribution=F17" ' % template_file)
        if enable_rollback:
            cmd += '-r '
        if timeout:
            cmd += '--timeout=%d ' % timeout
        preview_text = self.shell(cmd)

        required = [
            'stack_name',
            'id',
            'teststack',
            '1',
            'resources',
            'timeout_mins',
            'disable_rollback'
        ]

        for r in required:
            self.assertRegexpMatches(preview_text, r)

    def test_stack_preview(self):
        self._test_stack_preview()

    def test_stack_preview_timeout(self):
        self._test_stack_preview(300, True)

    def test_stack_create(self):
        self.register_keystone_auth_fixture()
        location = 'http://no.where/v1/tenant_id/stacks/teststack2/2'

        self.script_heat_list()
        self.requests.post('/stacks',
                           status_code=201,
                           request_headers={'X-Auth-Key': 'password',
                                            'X-Auth-User': 'username'},
                           headers={'location': location})


        template_file = os.path.join(TEST_VAR_DIR, 'minimal.template')
        create_text = self.shell(
            'stack-create teststack '
            '--template-file=%s '
            '--parameters="InstanceType=m1.large;DBUsername=wp;'
            'DBPassword=verybadpassword;KeyName=heat_key;'
            'LinuxDistribution=F17"' % template_file)

        required = [
            'stack_name',
            'id',
            'teststack',
            '1'
        ]

        for r in required:
            self.assertRegexpMatches(create_text, r)

    def test_stack_create_timeout(self):
        self.register_keystone_auth_fixture()
        template_file = os.path.join(TEST_VAR_DIR, 'minimal.template')
        template_data = open(template_file).read()

        expected_data = {
            'files': {},
            'disable_rollback': True,
            'parameters': {'DBUsername': 'wp',
                           'KeyName': 'heat_key',
                           'LinuxDistribution': 'F17"',
                           '"InstanceType': 'm1.large',
                           'DBPassword': 'verybadpassword'},
            'stack_name': 'teststack',
            'environment': {},
            'template': jsonutils.loads(template_data),
            'timeout_mins': 123}
        self.script_heat_list()

        location = 'http://no.where/v1/tenant_id/stacks/teststack2/2'

        m = self.requests.post('/stacks',
                               request_headers={'X-Auth-Key': 'password',
                                                'X-Auth-User': 'username'},
                               headers={'location': location},
                               status_code=201)

        create_text = self.shell(
            'stack-create teststack '
            '--template-file=%s '
            '--timeout=123 '
            '--parameters="InstanceType=m1.large;DBUsername=wp;'
            'DBPassword=verybadpassword;KeyName=heat_key;'
            'LinuxDistribution=F17"' % template_file)

        self.assertJsonEqual(expected_data, m.last_request)

        required = [
            'stack_name',
            'id',
            'teststack',
            '1'
        ]

        for r in required:
            self.assertRegexpMatches(create_text, r)

    def test_stack_update_timeout(self):
        self.register_keystone_auth_fixture()
        template_file = os.path.join(TEST_VAR_DIR, 'minimal.template')
        template_data = open(template_file).read()

        expected_data = {
            'files': {},
            'environment': {},
            'template': jsonutils.loads(template_data),
            'parameters': {'DBUsername': 'wp',
                           'KeyName': 'heat_key',
                           'LinuxDistribution': 'F17"',
                           '"InstanceType': 'm1.large',
                           'DBPassword': 'verybadpassword'},
            'timeout_mins': 123,
            'disable_rollback': True}

        self.script_heat_list()

        m = self.requests.put('/stacks/teststack2/2',
                              status_code=202,
                              text='The request is accepted for processing.',
                              request_headers={'X-Auth-Key': 'password',
                                               'X-Auth-User': 'username'})

        update_text = self.shell(
            'stack-update teststack2/2 '
            '--template-file=%s '
            '--timeout 123 '
            '--rollback off '
            '--parameters="InstanceType=m1.large;DBUsername=wp;'
            'DBPassword=verybadpassword;KeyName=heat_key;'
            'LinuxDistribution=F17"' % template_file)

        self.assertJsonEqual(expected_data, m.last_request)

        required = [
            'stack_name',
            'id',
            'teststack2',
            '1'
        ]
        for r in required:
            self.assertRegexpMatches(update_text, r)

    def test_stack_create_url(self):
        self.register_keystone_auth_fixture()

        self.m.StubOutWithMock(request, 'urlopen')
        request.urlopen('http://no.where/minimal.template').AndReturn(
            six.StringIO('{"AWSTemplateFormatVersion" : "2010-09-09"}'))

        self.m.ReplayAll()

        expected_data = {
            'files': {},
            'disable_rollback': True,
            'stack_name': 'teststack',
            'environment': {},
            'template': {"AWSTemplateFormatVersion": "2010-09-09"},
            'parameters': {'DBUsername': 'wp',
                           'KeyName': 'heat_key',
                           'LinuxDistribution': 'F17"',
                           '"InstanceType': 'm1.large',
                           'DBPassword': 'verybadpassword'}}

        self.script_heat_list()

        location = 'http://no.where/v1/tenant_id/stacks/teststack2/2'
        m = self.requests.post('/stacks',
                               status_code=201,
                               headers={'location': location},
                               request_headers={'X-Auth-Key': 'password',
                                                'X-Auth-User': 'username'})

        create_text = self.shell(
            'stack-create teststack '
            '--template-url=http://no.where/minimal.template '
            '--parameters="InstanceType=m1.large;DBUsername=wp;'
            'DBPassword=verybadpassword;KeyName=heat_key;'
            'LinuxDistribution=F17"')

        self.assertJsonEqual(expected_data, m.last_request)

        required = [
            'stack_name',
            'id',
            'teststack2',
            '2'
        ]
        for r in required:
            self.assertRegexpMatches(create_text, r)

    def test_stack_create_object(self):
        self.register_keystone_auth_fixture()
        template_file = os.path.join(TEST_VAR_DIR, 'minimal.template')
        template_data = open(template_file).read()

        self.script_heat_list()

        self.requests.get('http://no.where/container/minimal.template',
                          text=template_data)

        location = 'http://no.where/v1/tenant_id/stacks/teststack2/2'
        self.requests.post('/stacks',
                           status_code=201,
                           headers={'location': location},
                           request_headers={'X-Auth-Key': 'password',
                                            'X-Auth-User': 'username'},
                           text=template_data)

        create_text = self.shell(
            'stack-create teststack2 '
            '--template-object=http://no.where/container/minimal.template '
            '--parameters="InstanceType=m1.large;DBUsername=wp;'
            'DBPassword=verybadpassword;KeyName=heat_key;'
            'LinuxDistribution=F17"')

        required = [
            'stack_name',
            'id',
            'teststack2',
            '2'
        ]
        for r in required:
            self.assertRegexpMatches(create_text, r)

    def test_stack_adopt(self):
        self.register_keystone_auth_fixture()
        self.script_heat_list()

        location = 'http://no.where/v1/tenant_id/stacks/teststack/1'
        self.requests.post('/stacks',
                           headers={'location': location},
                           status_code=201,
                           request_headers={'X-Auth-Key': 'password',
                                            'X-Auth-User': 'username'})

        adopt_data_file = os.path.join(TEST_VAR_DIR, 'adopt_stack_data.json')
        adopt_text = self.shell(
            'stack-adopt teststack '
            '--adopt-file=%s '
            '--parameters="InstanceType=m1.large;DBUsername=wp;'
            'DBPassword=verybadpassword;KeyName=heat_key;'
            'LinuxDistribution=F17"' % (adopt_data_file))

        required = [
            'stack_name',
            'id',
            'teststack',
            '1'
        ]

        for r in required:
            self.assertRegexpMatches(adopt_text, r)

    def test_stack_adopt_without_data(self):
        self.register_keystone_auth_fixture()
        failed_msg = 'Need to specify --adopt-file'
        self.shell_error('stack-adopt teststack ', failed_msg)

    def test_stack_update_enable_rollback(self):
        self.register_keystone_auth_fixture()
        template_file = os.path.join(TEST_VAR_DIR, 'minimal.template')
        with open(template_file, 'rb') as f:
            template_data = jsonutils.load(f)
        expected_data = {'files': {},
                         'environment': {},
                         'template': template_data,
                         'disable_rollback': False,
                         'parameters': mox.IgnoreArg()
                         }
        self.script_heat_list()

        m = self.requests.put('/stacks/teststack2/2',
                              status_code=202,
                              text='The request is accepted for processing.',
                              request_headers={'X-Auth-Key': 'password',
                                               'X-Auth-User': 'username'})


        update_text = self.shell(
            'stack-update teststack2/2 '
            '--rollback on '
            '--template-file=%s '
            '--parameters="InstanceType=m1.large;DBUsername=wp;'
            'DBPassword=verybadpassword;KeyName=heat_key;'
            'LinuxDistribution=F17"' % template_file)

        self.assertJsonEqual(expected_data, m.last_request)

        required = [
            'stack_name',
            'id',
            'teststack2',
            '1'
        ]
        for r in required:
            self.assertRegexpMatches(update_text, r)

    def test_stack_update_disable_rollback(self):
        self.register_keystone_auth_fixture()
        template_file = os.path.join(TEST_VAR_DIR, 'minimal.template')
        with open(template_file, 'rb') as f:
            template_data = jsonutils.load(f)
        expected_data = {'files': {},
                         'environment': {},
                         'template': template_data,
                         'disable_rollback': True,
                         'parameters': mox.IgnoreArg()
                         }
        self.script_heat_list()

        m = self.requests.put('/stacks/teststack2',
                              status_code=202,
                              text='The request is accepted for processing.',
                              request_headers={'X-Auth-Key': 'password',
                                               'X-Auth-User': 'username'})

        update_text = self.shell(
            'stack-update teststack2 '
            '--template-file=%s '
            '--rollback off '
            '--parameters="InstanceType=m1.large;DBUsername=wp;'
            'DBPassword=verybadpassword;KeyName=heat_key;'
            'LinuxDistribution=F17"' % template_file)

        self.assertJsonEqual(expected_data, m.last_request)

        required = [
            'stack_name',
            'id',
            'teststack2',
            '1'
        ]
        for r in required:
            self.assertRegexpMatches(update_text, r)

    def test_stack_update_fault_rollback_value(self):
        self.register_keystone_auth_fixture()
        template_file = os.path.join(TEST_VAR_DIR, 'minimal.template')
        self.shell_error('stack-update teststack2/2 '
                         '--rollback Foo '
                         '--template-file=%s' % template_file,
                         "Unrecognized value 'Foo', acceptable values are:"
                         )

    def test_stack_update_rollback_default(self):
        self.register_keystone_auth_fixture()
        template_file = os.path.join(TEST_VAR_DIR, 'minimal.template')
        with open(template_file, 'rb') as f:
            template_data = jsonutils.load(f)
        expected_data = {'files': {},
                         'environment': {},
                         'template': template_data,
                         'parameters': mox.IgnoreArg()
                         }
        self.script_heat_list()

        m = self.requests.put('/stacks/teststack2',
                              status_code=202,
                              text='The request is accepted for processing.',
                              request_headers={'X-Auth-Key': 'password',
                                               'X-Auth-User': 'username'})

        update_text = self.shell(
            'stack-update teststack2 '
            '--template-file=%s '
            '--parameters="InstanceType=m1.large;DBUsername=wp;'
            'DBPassword=verybadpassword;KeyName=heat_key;'
            'LinuxDistribution=F17"' % template_file)

        self.assertJsonEqual(expected_data, m.last_request)

        required = [
            'stack_name',
            'id',
            'teststack2',
            '2'
        ]
        for r in required:
            self.assertRegexpMatches(update_text, r)

    def test_stack_update_with_existing_parameters(self):
        self.register_keystone_auth_fixture()
        template_file = os.path.join(TEST_VAR_DIR, 'minimal.template')
        template_data = open(template_file).read()
        expected_data = {
            'files': {},
            'environment': {},
            'template': jsonutils.loads(template_data),
            'parameters': {},
            'disable_rollback': False}

        self.script_heat_list()

        m = self.requests.patch('/stacks/teststack2/2',
                                request_headers={'X-Auth-Key': 'password',
                                                 'X-Auth-User': 'username'},
                                status_code=202,
                                text='The request is accepted for processing.')

        update_text = self.shell(
            'stack-update teststack2/2 '
            '--template-file=%s '
            '--enable-rollback '
            '--existing' % template_file)

        self.assertJsonEqual(expected_data, m.last_request)

        required = [
            'stack_name',
            'id',
            'teststack2',
            '1'
        ]
        for r in required:
            self.assertRegexpMatches(update_text, r)

    def test_stack_update_with_patched_existing_parameters(self):
        self.register_keystone_auth_fixture()
        template_file = os.path.join(TEST_VAR_DIR, 'minimal.template')
        template_data = open(template_file).read()
        expected_data = {
            'files': {},
            'environment': {},
            'template': jsonutils.loads(template_data),
            'parameters': {'"KeyPairName': 'updated_key"'},
            'disable_rollback': False}

        self.script_heat_list()

        m = self.requests.patch('/stacks/teststack2/2',
                                text='The request is accepted for processing.',
                                status_code=202,
                                request_headers={'X-Auth-Key': 'password',
                                                 'X-Auth-User': 'username'})

        update_text = self.shell(
            'stack-update teststack2/2 '
            '--template-file=%s '
            '--enable-rollback '
            '--parameters="KeyPairName=updated_key" '
            '--existing' % template_file)

        self.assertJsonEqual(expected_data, m.last_request)

        required = [
            'stack_name',
            'id',
            'teststack2',
            '1'
        ]
        for r in required:
            self.assertRegexpMatches(update_text, r)

    def test_stack_update_with_existing_and_default_parameters(self):
        self.register_keystone_auth_fixture()
        template_file = os.path.join(TEST_VAR_DIR, 'minimal.template')
        template_data = open(template_file).read()
        expected_data = {
            'files': {},
            'environment': {},
            'template': jsonutils.loads(template_data),
            'parameters': {},
            'clear_parameters': ['InstanceType', 'DBUsername',
                                 'DBPassword', 'KeyPairName',
                                 'LinuxDistribution'],
            'disable_rollback': False}

        self.script_heat_list()

        m = self.requests.patch('/stacks/teststack2/2',
                                status_code=202,
                                text='The request is accepted for processing.',
                                request_headers={'X-Auth-Key': 'password',
                                                 'X-Auth-User': 'username'})

        update_text = self.shell(
            'stack-update teststack2/2 '
            '--template-file=%s '
            '--enable-rollback '
            '--existing '
            '--clear-parameter=InstanceType '
            '--clear-parameter=DBUsername '
            '--clear-parameter=DBPassword '
            '--clear-parameter=KeyPairName '
            '--clear-parameter=LinuxDistribution' % template_file)

        self.assertJsonEqual(expected_data, m.last_request)

        required = [
            'stack_name',
            'id',
            'teststack2',
            '1'
        ]
        for r in required:
            self.assertRegexpMatches(update_text, r)

    def test_stack_update_with_patched_and_default_parameters(self):
        self.register_keystone_auth_fixture()
        template_file = os.path.join(TEST_VAR_DIR, 'minimal.template')
        template_data = open(template_file).read()
        expected_data = {
            'files': {},
            'environment': {},
            'template': jsonutils.loads(template_data),
            'parameters': {'"KeyPairName': 'updated_key"'},
            'clear_parameters': ['InstanceType', 'DBUsername',
                                 'DBPassword', 'KeyPairName',
                                 'LinuxDistribution'],
            'disable_rollback': False}

        self.script_heat_list()

        m = self.requests.patch('/stacks/teststack2/2',
                                status_code=202,
                                text='The request is accepted for processing.',
                                request_headers={'X-Auth-Key': 'password',
                                                 'X-Auth-User': 'username'})

        update_text = self.shell(
            'stack-update teststack2/2 '
            '--template-file=%s '
            '--enable-rollback '
            '--existing '
            '--parameters="KeyPairName=updated_key" '
            '--clear-parameter=InstanceType '
            '--clear-parameter=DBUsername '
            '--clear-parameter=DBPassword '
            '--clear-parameter=KeyPairName '
            '--clear-parameter=LinuxDistribution' % template_file)

        self.assertJsonEqual(expected_data, m.last_request)

        required = [
            'stack_name',
            'id',
            'teststack2',
            '1'
        ]
        for r in required:
            self.assertRegexpMatches(update_text, r)

    def test_stack_cancel_update(self):
        self.register_keystone_auth_fixture()
        expected_data = {'cancel_update': None}
        self.script_heat_list()

        m = self.requests.post('/stacks/teststack2/actions',
                               status_code=202,
                               text='The request is accepted for processing.')

        update_text = self.shell('stack-cancel-update teststack2')

        self.assertJsonEqual(expected_data, m.last_request)

        required = [
            'stack_name',
            'id',
            'teststack2',
            '1'
        ]
        for r in required:
            self.assertRegexpMatches(update_text, r)

    def test_stack_check(self):
        self.register_keystone_auth_fixture()
        expected_data = {'check': None}
        self.script_heat_list()

        m = self.requests.post('/stacks/teststack2/actions',
                               status_code=202,
                               text='The request is accepted for processing.')

        check_text = self.shell('action-check teststack2')

        self.assertJsonEqual(expected_data, m.last_request)

        required = [
            'stack_name',
            'id',
            'teststack2',
            '1'
        ]
        for r in required:
            self.assertRegexpMatches(check_text, r)

    def test_stack_delete(self):
        self.register_keystone_auth_fixture()
        self.script_heat_list()

        self.requests.delete('/stacks/teststack2/2',
                             status_code=204)

        delete_text = self.shell('stack-delete teststack2/2')

        required = [
            'stack_name',
            'id',
            'teststack',
            '1'
        ]
        for r in required:
            self.assertRegexpMatches(delete_text, r)

    def test_stack_delete_multiple(self):
        self.register_keystone_auth_fixture()
        self.script_heat_list()

        self.requests.delete('/stacks/teststack1/1', status_code=204)
        self.requests.delete('/stacks/teststack2/2', status_code=204)

        delete_text = self.shell('stack-delete teststack1/1 teststack2/2')

        required = [
            'stack_name',
            'id',
            'teststack',
            '1'
        ]
        for r in required:
            self.assertRegexpMatches(delete_text, r)

    def test_build_info(self):
        self.register_keystone_auth_fixture()
        resp_dict = {
            'build_info': {
                'api': {'revision': 'api_revision'},
                'engine': {'revision': 'engine_revision'}
            }
        }

        self.requests.get('/build_info',
                          headers={'Content-Type': 'application/json'},
                          json=resp_dict)

        build_info_text = self.shell('build-info')

        required = [
            'api',
            'engine',
            'revision',
            'api_revision',
            'engine_revision',
        ]
        for r in required:
            self.assertRegexpMatches(build_info_text, r)

    def test_stack_snapshot(self):
        self.register_keystone_auth_fixture()

        stack_dict = {"stack": {
            "id": "1",
            "stack_name": "teststack",
            "stack_status": 'CREATE_COMPLETE',
            "creation_time": "2012-10-25T01:58:47Z"
        }}

        resp_dict = {"snapshot": {
            "id": "1",
            "creation_time": "2012-10-25T01:58:47Z"
        }}

        self.requests.get('/stacks/teststack/1',
                          headers={'Content-Type': 'application/json'},
                          json=stack_dict)
        self.requests.post('/stacks/teststack/1/snapshots',
                          headers={'Content-Type': 'application/json'},
                          json=resp_dict)

        resp = self.shell('stack-snapshot teststack/1')
        self.assertEqual(resp_dict, jsonutils.loads(resp))

    def test_snapshot_show(self):
        self.register_keystone_auth_fixture()

        stack_dict = {"stack": {
            "id": "1",
            "stack_name": "teststack",
            "stack_status": 'CREATE_COMPLETE',
            "creation_time": "2012-10-25T01:58:47Z"
        }}

        resp_dict = {"snapshot": {
            "id": "2",
            "creation_time": "2012-10-25T01:58:47Z"
        }}

        self.requests.get('/stacks/teststack/1',
                          headers={'Content-Type': 'application/json'},
                          json=stack_dict)
        self.requests.get('/stacks/teststack/1/snapshots/2',
                          headers={'Content-Type': 'application/json'},
                          json=resp_dict)

        resp = self.shell('snapshot-show teststack/1 2')
        self.assertEqual(resp_dict, jsonutils.loads(resp))

    def test_snapshot_delete(self):
        self.register_keystone_auth_fixture()

        stack_dict = {"stack": {
            "id": "1",
            "stack_name": "teststack",
            "stack_status": 'CREATE_COMPLETE',
            "creation_time": "2012-10-25T01:58:47Z"
        }}

        resp_dict = {"snapshot": {
            "id": "2",
            "creation_time": "2012-10-25T01:58:47Z"
        }}

        self.requests.get('/stacks/teststack/1',
                          status_code=204,
                          headers={'Content-Type': 'application/json'},
                          json=stack_dict)
        self.requests.delete('/stacks/teststack/1/snapshots/2',
                             status_code=204,
                             headers={'Content-Type': 'application/json'},
                             json=resp_dict)

        resp = self.shell('snapshot-delete teststack/1 2')
        self.assertEqual("", resp)

    def test_stack_restore(self):
        self.register_keystone_auth_fixture()

        stack_dict = {"stack": {
            "id": "1",
            "stack_name": "teststack",
            "stack_status": 'CREATE_COMPLETE',
            "creation_time": "2012-10-25T01:58:47Z"
        }}

        self.requests.get('/stacks/teststack/1',
                          json=stack_dict,
                          headers={'Content-Type': 'application/json'})
        url = '/stacks/teststack/1/snapshots/2/restore'
        self.requests.post(url, status_code=204, json={})

        resp = self.shell('stack-restore teststack/1 2')
        self.assertEqual("", resp)

    def test_snapshot_list(self):
        self.register_keystone_auth_fixture()

        stack_dict = {"stack": {
            "id": "1",
            "stack_name": "teststack",
            "stack_status": 'CREATE_COMPLETE',
            "creation_time": "2012-10-25T01:58:47Z"
        }}

        resp_dict = {"snapshots": [{
            "id": "2",
            "name": "snap1",
            "status": "COMPLETE",
            "status_reason": "",
            "data": {},
            "creation_time": "2014-12-05T01:25:52Z"
        }]}

        self.requests.get('/stacks/teststack/1',
                          headers={'Content-Type': 'application/json'},
                          json=stack_dict)
        self.requests.get('/stacks/teststack/1/snapshots',
                          headers={'Content-Type': 'application/json'},
                          json=resp_dict)

        list_text = self.shell('snapshot-list teststack/1')

        required = [
            'id',
            'name',
            'status',
            'status_reason',
            'data',
            'creation_time',
            '2',
            'COMPLETE',
            '{}',
            '2014-12-05T01:25:52Z',
        ]
        for r in required:
            self.assertRegexpMatches(list_text, r)


class ShellTestEvents(ShellBase):

    def setUp(self):
        super(ShellTestEvents, self).setUp()
        self.set_fake_env(FAKE_ENV_KEYSTONE_V2)

    scenarios = [
        ('integer_id', dict(
            event_id_one='24',
            event_id_two='42')),
        ('uuid_id', dict(
            event_id_one='3d68809e-c4aa-4dc9-a008-933823d2e44f',
            event_id_two='43b68bae-ed5d-4aed-a99f-0b3d39c2418a'))]

    def test_event_list(self):
        self.register_keystone_auth_fixture()
        resp_dict = {"events": [
                     {"event_time": "2013-12-05T14:14:30Z",
                      "id": self.event_id_one,
                      "links": [{"href": "http://heat.example.com:8004/foo",
                                 "rel": "self"},
                                {"href": "http://heat.example.com:8004/foo2",
                                 "rel": "resource"},
                                {"href": "http://heat.example.com:8004/foo3",
                                 "rel": "stack"}],
                      "logical_resource_id": "aResource",
                      "physical_resource_id": None,
                      "resource_name": "aResource",
                      "resource_status": "CREATE_IN_PROGRESS",
                      "resource_status_reason": "state changed"},
                     {"event_time": "2013-12-05T14:14:30Z",
                      "id": self.event_id_two,
                      "links": [{"href": "http://heat.example.com:8004/foo",
                                 "rel": "self"},
                                {"href": "http://heat.example.com:8004/foo2",
                                 "rel": "resource"},
                                {"href": "http://heat.example.com:8004/foo3",
                                 "rel": "stack"}],
                      "logical_resource_id": "aResource",
                      "physical_resource_id":
                      "bce15ec4-8919-4a02-8a90-680960fb3731",
                      "resource_name": "aResource",
                      "resource_status": "CREATE_COMPLETE",
                      "resource_status_reason": "state changed"}]}

        stack_id = 'teststack/1'
        resource_name = 'testresource/1'

        url = '/stacks/%s/resources/%s/events' % (
            parse.quote(stack_id, ''),
            parse.quote(encodeutils.safe_encode(resource_name), ''))

        self.requests.get(url,
                          headers={'Content-Type': 'application/json'},
                          json=resp_dict)

        event_list_text = self.shell('event-list {0} --resource {1}'.format(
                                     stack_id, resource_name))

        required = [
            'resource_name',
            'id',
            'resource_status_reason',
            'resource_status',
            'event_time',
            'aResource',
            self.event_id_one,
            self.event_id_two,
            'state changed',
            'CREATE_IN_PROGRESS',
            'CREATE_COMPLETE',
            '2013-12-05T14:14:30Z',
            '2013-12-05T14:14:30Z',
        ]
        for r in required:
            self.assertRegexpMatches(event_list_text, r)

    def test_event_show(self):
        self.register_keystone_auth_fixture()
        resp_dict = {"event":
                     {"event_time": "2013-12-05T14:14:30Z",
                      "id": self.event_id_one,
                      "links": [{"href": "http://heat.example.com:8004/foo",
                                 "rel": "self"},
                                {"href": "http://heat.example.com:8004/foo2",
                                 "rel": "resource"},
                                {"href": "http://heat.example.com:8004/foo3",
                                 "rel": "stack"}],
                      "logical_resource_id": "aResource",
                      "physical_resource_id": None,
                      "resource_name": "aResource",
                      "resource_properties": {"admin_user": "im_powerful",
                                              "availability_zone": "nova"},
                      "resource_status": "CREATE_IN_PROGRESS",
                      "resource_status_reason": "state changed",
                      "resource_type": "OS::Nova::Server"
                      }}

        stack_id = 'teststack/1'
        resource_name = 'testresource/1'

        url = '/stacks/%s/resources/%s/events/%s' % (
            parse.quote(stack_id, ''),
            parse.quote(encodeutils.safe_encode(resource_name), ''),
            parse.quote(self.event_id_one, '')
        )

        self.requests.get(HEAT_URL + url,
                          headers={'Content-Type': 'application/json'},
                          json=resp_dict)

        event_list_text = self.shell('event-show {0} {1} {2}'.format(
                                     stack_id, resource_name,
                                     self.event_id_one))

        required = [
            'Property',
            'Value',
            'event_time',
            '2013-12-05T14:14:30Z',
            'id',
            self.event_id_one,
            'links',
            'http://heat.example.com:8004/foo[0-9]',
            'logical_resource_id',
            'physical_resource_id',
            'resource_name',
            'aResource',
            'resource_properties',
            'admin_user',
            'availability_zone',
            'resource_status',
            'CREATE_IN_PROGRESS',
            'resource_status_reason',
            'state changed',
            'resource_type',
            'OS::Nova::Server',
        ]
        for r in required:
            self.assertRegexpMatches(event_list_text, r)


class ShellTestResources(ShellBase):

    def setUp(self):
        super(ShellTestResources, self).setUp()
        self.set_fake_env(FAKE_ENV_KEYSTONE_V2)

    def _test_resource_list(self, with_resource_name):
        self.register_keystone_auth_fixture()
        resp_dict = {"resources": [
                     {"links": [{"href": "http://heat.example.com:8004/foo",
                                 "rel": "self"},
                                {"href": "http://heat.example.com:8004/foo2",
                                 "rel": "resource"}],
                      "logical_resource_id": "aLogicalResource",
                      "physical_resource_id":
                      "43b68bae-ed5d-4aed-a99f-0b3d39c2418a",
                      "resource_status": "CREATE_COMPLETE",
                      "resource_status_reason": "state changed",
                      "resource_type": "OS::Nova::Server",
                      "updated_time": "2014-01-06T16:14:26Z"}]}
        if with_resource_name:
            resp_dict["resources"][0]["resource_name"] = "aResource"
        stack_id = 'teststack/1'

        self.requests.get('%s/stacks/%s/resources' % (HEAT_URL, stack_id),
                          headers={'Content-Type': 'application/json'},
                          json=resp_dict)

        resource_list_text = self.shell('resource-list {0}'.format(stack_id))

        required = [
            'physical_resource_id',
            'resource_type',
            'resource_status',
            'updated_time',
            '43b68bae-ed5d-4aed-a99f-0b3d39c2418a',
            'OS::Nova::Server',
            'CREATE_COMPLETE',
            '2014-01-06T16:14:26Z'
        ]
        if with_resource_name:
            required.append('resource_name')
            required.append('aResource')
        else:
            required.append('logical_resource_id')
            required.append("aLogicalResource")

        for r in required:
            self.assertRegexpMatches(resource_list_text, r)

    def test_resource_list(self):
        self._test_resource_list(True)

    def test_resource_list_no_resource_name(self):
        self._test_resource_list(False)

    def test_resource_list_empty(self):
        self.register_keystone_auth_fixture()
        resp_dict = {"resources": []}
        stack_id = 'teststack/1'

        self.requests.get('%s/stacks/%s/resources' % (HEAT_URL, stack_id),
                          headers={'Content-Type': 'application/json'},
                          json=resp_dict)

        resource_list_text = self.shell('resource-list {0}'.format(stack_id))

        self.assertEqual('''\
+---------------+----------------------+---------------+-----------------+\
--------------+
| resource_name | physical_resource_id | resource_type | resource_status |\
 updated_time |
+---------------+----------------------+---------------+-----------------+\
--------------+
+---------------+----------------------+---------------+-----------------+\
--------------+
''', resource_list_text)

    def test_resource_list_nested(self):
        self.register_keystone_auth_fixture()
        resp_dict = {"resources": [{
            "resource_name": "foobar",
            "parent_resource": "my_parent_resource",
        }]}
        stack_id = 'teststack/1'

        url = '%s/stacks/%s/resources?nested_depth=99'
        self.requests.get(url % (HEAT_URL, stack_id),
                          headers={'Content-Type': 'application/json'},
                          json=resp_dict)

        shell_cmd = 'resource-list {0} --nested-depth {1}'.format(stack_id, 99)
        resource_list_text = self.shell(shell_cmd)

        required = [
            'resource_name', 'foobar',
            'parent_resource', 'my_parent_resource',
        ]
        for field in required:
            self.assertRegexpMatches(resource_list_text, field)

    def test_resource_show(self):
        self.register_keystone_auth_fixture()
        resp_dict = {"resource":
                     {"description": "",
                      "links": [{"href": "http://heat.example.com:8004/foo",
                                 "rel": "self"},
                                {"href": "http://heat.example.com:8004/foo2",
                                 "rel": "resource"}],
                      "logical_resource_id": "aResource",
                      "physical_resource_id":
                      "43b68bae-ed5d-4aed-a99f-0b3d39c2418a",
                      "required_by": [],
                      "resource_name": "aResource",
                      "resource_status": "CREATE_COMPLETE",
                      "resource_status_reason": "state changed",
                      "resource_type": "OS::Nova::Server",
                      "updated_time": "2014-01-06T16:14:26Z"}}

        stack_id = 'teststack/1'
        resource_name = 'aResource'

        url = '%s/stacks/%s/resources/%s' % (
            HEAT_URL,
            parse.quote(stack_id, ''),
            parse.quote(encodeutils.safe_encode(resource_name), '')
        )

        self.requests.get(url,
                          headers={'Content-Type': 'application/json'},
                          json=resp_dict)

        resource_show_text = self.shell('resource-show {0} {1}'.format(
                                        stack_id, resource_name))

        required = [
            'description',
            'links',
            'http://heat.example.com:8004/foo[0-9]',
            'logical_resource_id',
            'aResource',
            'physical_resource_id',
            '43b68bae-ed5d-4aed-a99f-0b3d39c2418a',
            'required_by',
            'resource_name',
            'aResource',
            'resource_status',
            'CREATE_COMPLETE',
            'resource_status_reason',
            'state changed',
            'resource_type',
            'OS::Nova::Server',
            'updated_time',
            '2014-01-06T16:14:26Z',
        ]
        for r in required:
            self.assertRegexpMatches(resource_show_text, r)

    def test_resource_signal(self):
        self.register_keystone_auth_fixture()

        stack_id = 'teststack/1'
        resource_name = 'aResource'
        url = '%s/stacks/%s/resources/%s/signal' % (
            HEAT_URL,
            parse.quote(stack_id, ''),
            parse.quote(encodeutils.safe_encode(resource_name), '')
        )

        self.requests.post(url,
                           headers={'Content-Type': 'application/json'},
                           json={})

        text = self.shell(
            'resource-signal {0} {1} -D {{"message":"Content"}}'.format(
                stack_id, resource_name))

        self.assertJsonEqual({'message': 'Content'},
                             self.requests.last_request)
        self.assertEqual("", text)

    def test_resource_signal_no_data(self):
        self.register_keystone_auth_fixture()

        stack_id = 'teststack/1'
        resource_name = 'aResource'
        url = '%s/stacks/%s/resources/%s/signal' % (
            HEAT_URL,
            parse.quote(stack_id, ''),
            parse.quote(encodeutils.safe_encode(resource_name), '')
        )
        self.requests.post(url, json={})

        text = self.shell(
            'resource-signal {0} {1}'.format(stack_id, resource_name))
        self.assertEqual("", text)

    def test_resource_signal_no_json(self):
        self.register_keystone_auth_fixture()
        stack_id = 'teststack/1'
        resource_name = 'aResource'

        error = self.assertRaises(
            exc.CommandError, self.shell,
            'resource-signal {0} {1} -D [2'.format(
                stack_id, resource_name))
        self.assertIn('Data should be in JSON format', str(error))

    def test_resource_signal_no_dict(self):
        self.register_keystone_auth_fixture()
        stack_id = 'teststack/1'
        resource_name = 'aResource'

        error = self.assertRaises(
            exc.CommandError, self.shell,
            'resource-signal {0} {1} -D "message"'.format(
                stack_id, resource_name))
        self.assertEqual('Data should be a JSON dict', str(error))

    def test_resource_signal_both_data(self):
        self.register_keystone_auth_fixture()
        stack_id = 'teststack/1'
        resource_name = 'aResource'

        error = self.assertRaises(
            exc.CommandError, self.shell,
            'resource-signal {0} {1} -D "message" -f foo'.format(
                stack_id, resource_name))
        self.assertEqual('Can only specify one of data and data-file',
                         str(error))

    def test_resource_signal_data_file(self):
        self.register_keystone_auth_fixture()

        stack_id = 'teststack/1'
        resource_name = 'aResource'
        url = '%s/stacks/%s/resources/%s/signal' % (
            HEAT_URL,
            parse.quote(stack_id, ''),
            parse.quote(encodeutils.safe_encode(resource_name), '')
        )

        self.requests.post(url, json={})

        with tempfile.NamedTemporaryFile() as data_file:
            data_file.write(b'{"message":"Content"}')
            data_file.flush()
            text = self.shell(
                'resource-signal {0} {1} -f {2}'.format(
                    stack_id, resource_name, data_file.name))
            self.assertEqual("", text)

        self.assertJsonEqual({'message': 'Content'},
                             self.requests.last_request)


class ShellTestResourceTypes(ShellBase):
    def setUp(self):
        super(ShellTestResourceTypes, self).setUp()
        self.set_fake_env(FAKE_ENV_KEYSTONE_V3)

    def test_resource_type_template_yaml(self):
        self.register_keystone_auth_fixture()
        resp_dict = {"heat_template_version": "2013-05-23",
                     "parameters": {},
                     "resources": {},
                     "outputs": {}}

        url = HEAT_URL + '/resource_types/OS%3A%3ANova%3A%3AKeyPair/template'
        self.requests.get(url,
                          headers={'Content-Type': 'application/json'},
                          json=resp_dict)

        show_text = self.shell(
            'resource-type-template -F yaml OS::Nova::KeyPair')
        required = [
            "heat_template_version: '2013-05-23'",
            "outputs: {}",
            "parameters: {}",
            "resources: {}"
        ]
        for r in required:
            self.assertRegexpMatches(show_text, r)

    def test_resource_type_template_json(self):
        self.register_keystone_auth_fixture()
        resp_dict = {"AWSTemplateFormatVersion": "2013-05-23",
                     "Parameters": {},
                     "Resources": {},
                     "Outputs": {}}

        url = HEAT_URL + '/resource_types/OS%3A%3ANova%3A%3AKeyPair/template'
        self.requests.get(url,
                          headers={'Content-Type': 'application/json'},
                          json=resp_dict)

        show_text = self.shell(
            'resource-type-template -F json OS::Nova::KeyPair')
        required = [
            '{',
            '  "AWSTemplateFormatVersion": "2013-05-23"',
            '  "Outputs": {}',
            '  "Resources": {}',
            '  "Parameters": {}',
            '}'
        ]
        for r in required:
            self.assertRegexpMatches(show_text, r)


class ShellTestBuildInfo(ShellBase):

    def setUp(self):
        super(ShellTestBuildInfo, self).setUp()
        self._set_fake_env()

    def _set_fake_env(self):
        '''Patch os.environ to avoid required auth info.'''
        self.set_fake_env(FAKE_ENV_KEYSTONE_V2)

    def test_build_info(self):
        self.register_keystone_auth_fixture()
        resp_dict = {
            'build_info': {
                'api': {'revision': 'api_revision'},
                'engine': {'revision': 'engine_revision'}
            }
        }

        self.requests.get('%s/build_info' % HEAT_URL,
                          headers={'Content-Type': 'application/json'},
                          json=resp_dict)

        build_info_text = self.shell('build-info')

        required = [
            'api',
            'engine',
            'revision',
            'api_revision',
            'engine_revision',
        ]
        for r in required:
            self.assertRegexpMatches(build_info_text, r)


class ShellTestToken(ShellTestUserPass):

    # Rerun all ShellTestUserPass test with token auth
    def setUp(self):
        self.token = 'a_token'
        super(ShellTestToken, self).setUp()

    def _set_fake_env(self):
        fake_env = {
            'OS_AUTH_TOKEN': self.token,
            'OS_TENANT_ID': 'tenant_id',
            'OS_AUTH_URL': BASE_URL,
            # Note we also set username/password, because create/update
            # pass them even if we have a token to support storing credentials
            # Hopefully at some point we can remove this and move to only
            # storing trust id's in heat-engine instead..
            'OS_USERNAME': 'username',
            'OS_PASSWORD': 'password'
        }
        self.set_fake_env(fake_env)


class ShellTestUserPassKeystoneV3(ShellTestUserPass):

    def _set_fake_env(self):
        self.set_fake_env(FAKE_ENV_KEYSTONE_V3)


class ShellTestStandaloneToken(ShellTestUserPass):

    # Rerun all ShellTestUserPass test in standalone mode, where we
    # specify --os-no-client-auth, a token and Heat endpoint
    def setUp(self):
        self.token = 'a_token'
        super(ShellTestStandaloneToken, self).setUp()

    def _set_fake_env(self):
        fake_env = {
            'OS_AUTH_TOKEN': self.token,
            'OS_NO_CLIENT_AUTH': 'True',
            'HEAT_URL': 'http://no.where',
            'OS_AUTH_URL': BASE_URL,
            # Note we also set username/password, because create/update
            # pass them even if we have a token to support storing credentials
            # Hopefully at some point we can remove this and move to only
            # storing trust id's in heat-engine instead..
            'OS_USERNAME': 'username',
            'OS_PASSWORD': 'password'
        }
        self.set_fake_env(fake_env)

    def test_bad_template_file(self):
        self.register_keystone_auth_fixture()
        failed_msg = 'Error parsing template '

        with tempfile.NamedTemporaryFile() as bad_json_file:
            bad_json_file.write(b"{foo:}")
            bad_json_file.flush()
            self.shell_error("stack-create ts -f %s" % bad_json_file.name,
                             failed_msg)

        with tempfile.NamedTemporaryFile() as bad_json_file:
            bad_json_file.write(b'{"foo": None}')
            bad_json_file.flush()
            self.shell_error("stack-create ts -f %s" % bad_json_file.name,
                             failed_msg)

    def test_commandline_args_passed_to_requests(self):
        """Check that we have sent the proper arguments to requests."""
        self.register_keystone_auth_fixture()

        resp_dict = {"stacks": [
            {
                "id": "1",
                "stack_name": "teststack",
                "stack_owner": "testowner",
                "project": "testproject",
                "stack_status": 'CREATE_COMPLETE',
                "creation_time": "2014-10-15T01:58:47Z"
            }]}

        self.requests.get('http://no.where/stacks?',
                          request_headers={'Content-Type': 'application/json',
                                           'Accept': 'application/json',
                                           'X-Auth-Token': self.token,
                                           'X-Auth-Url': BASE_URL,
                                           'User-Agent': 'python-heatclient'},
                          headers={'Content-Type': 'application/json'},
                          json=resp_dict)

        list_text = self.shell('stack-list')
        required = [
            'id',
            'stack_status',
            'creation_time',
            'teststack',
            '1',
            'CREATE_COMPLETE',
        ]
        for r in required:
            self.assertRegexpMatches(list_text, r)
        self.assertNotRegexpMatches(list_text, 'parent')


class MockShellBase(TestCase):

    def setUp(self):
        super(MockShellBase, self).setUp()

        # Some tests set exc.verbose = 1, so reset on cleanup
        def unset_exc_verbose():
            exc.verbose = 0

        self.addCleanup(unset_exc_verbose)

    def shell(self, argstr):
        orig = sys.stdout
        try:
            sys.stdout = six.StringIO()
            _shell = heatclient.shell.HeatShell()
            _shell.main(argstr.split())
            self.subcommands = _shell.subcommands.keys()
        except SystemExit:
            exc_type, exc_value, exc_traceback = sys.exc_info()
            self.assertEqual(0, exc_value.code)
        finally:
            out = sys.stdout.getvalue()
            sys.stdout.close()
            sys.stdout = orig

        return out


class MockShellTestUserPass(MockShellBase):

    def setUp(self):
        super(MockShellTestUserPass, self).setUp()
        self._set_fake_env()

    def _set_fake_env(self):
        self.set_fake_env(FAKE_ENV_KEYSTONE_V2)

    def test_stack_list_with_args(self):
        self.register_keystone_auth_fixture()

        resp_dict = {"stacks": [
            {
                "id": "1",
                "stack_name": "teststack",
                "stack_owner": "testowner",
                "project": "testproject",
                "stack_status": 'CREATE_COMPLETE',
                "creation_time": "2012-10-25T01:58:47Z"
            },
            {
                "id": "2",
                "stack_name": "teststack2",
                "stack_owner": "testowner",
                "project": "testproject",
                "stack_status": 'IN_PROGRESS',
                "creation_time": "2012-10-25T01:58:47Z"
            }]
        }

        m = self.requests.get('/stacks',
                              headers={'Content-Type': 'application/json'},
                              json=resp_dict)

        list_text = self.shell('stack-list'
                               ' --limit 2'
                               ' --marker fake_id'
                               ' --filters=status=COMPLETE'
                               ' --filters=status=FAILED'
                               ' --global-tenant'
                               ' --show-deleted')

        required = [
            'stack_owner',
            'project',
            'testproject',
            'teststack',
            'teststack2',
        ]
        for r in required:
            self.assertRegexpMatches(list_text, r)
        self.assertNotRegexpMatches(list_text, 'parent')

        self.assertEqual(1, len(m.request_history))
        expected_query_dict = {'limit': ['2'],
                               'status': ['complete', 'failed'],
                               'marker': ['fake_id'],
                               'global_tenant': ['true'],
                               'show_deleted': ['true']}
        self.assertEqual(expected_query_dict, self.requests.last_request.qs)


class MockShellTestToken(MockShellTestUserPass):

    # Rerun all ShellTestUserPass test with token auth
    def setUp(self):
        self.token = 'a_token'
        super(MockShellTestToken, self).setUp()

    def _set_fake_env(self):
        fake_env = {
            'OS_AUTH_TOKEN': self.token,
            'OS_TENANT_ID': 'tenant_id',
            'OS_AUTH_URL': BASE_URL,
            # Note we also set username/password, because create/update
            # pass them even if we have a token to support storing credentials
            # Hopefully at some point we can remove this and move to only
            # storing trust id's in heat-engine instead..
            'OS_USERNAME': 'username',
            'OS_PASSWORD': 'password'
        }
        self.set_fake_env(fake_env)


class MockShellTestUserPassKeystoneV3(MockShellTestUserPass):

    def _set_fake_env(self):
        self.set_fake_env(FAKE_ENV_KEYSTONE_V3)


class MockShellTestStandaloneToken(MockShellTestUserPass):

    # Rerun all ShellTestUserPass test in standalone mode, where we
    # specify --os-no-client-auth, a token and Heat endpoint
    def setUp(self):
        self.token = 'a_token'
        super(MockShellTestStandaloneToken, self).setUp()

    def _set_fake_env(self):
        fake_env = {
            'OS_AUTH_TOKEN': self.token,
            'OS_NO_CLIENT_AUTH': 'True',
            'HEAT_URL': HEAT_URL,
            'OS_AUTH_URL': BASE_URL,
            # Note we also set username/password, because create/update
            # pass them even if we have a token to support storing credentials
            # Hopefully at some point we can remove this and move to only
            # storing trust id's in heat-engine instead..
            'OS_USERNAME': 'username',
            'OS_PASSWORD': 'password'
        }
        self.set_fake_env(fake_env)
