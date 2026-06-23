# Copyright 2026 Nectar
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

import os
import shutil
import tempfile

from manila.privsep import os as privsep_os
from manila import test


class ExpireNFSClientsTestCase(test.TestCase):
    """Tests the (non-privileged) NFS client expiry helper."""

    def setUp(self):
        super(ExpireNFSClientsTestCase, self).setUp()
        self.clients_path = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.clients_path, ignore_errors=True)
        # Device-mapper devices use major 253 (0xfd).
        self.major = 253
        self.minor = 1

    def _add_client(self, client_id, states):
        client_dir = os.path.join(self.clients_path, client_id)
        os.makedirs(client_dir)
        with open(os.path.join(client_dir, 'states'), 'w') as f:
            f.write(states)
        # The real kernel ctl file already exists; emulate that.
        open(os.path.join(client_dir, 'ctl'), 'w').close()
        return client_dir

    def _ctl_contents(self, client_id):
        with open(os.path.join(self.clients_path, client_id, 'ctl')) as f:
            return f.read()

    def test_expires_only_clients_holding_the_device(self):
        # Holds our device (253:1) -> must be expired.
        holder = self._add_client(
            '9', '- 0x123: { type: open, access: rw, deny: --, '
                 'superblock: "fd:01:42", filename: "/share/file" }\n')
        # Holds a different device (253:5) -> must be left alone.
        other = self._add_client(
            '11', '- 0x456: { type: open, access: rw, deny: --, '
                  'superblock: "fd:05:42", filename: "/other/file" }\n')

        expired = privsep_os._expire_nfs_clients_holding_dev(
            self.major, self.minor, self.clients_path)

        self.assertEqual(['9'], expired)
        self.assertEqual('expire\n', self._ctl_contents('9'))
        self.assertEqual('', self._ctl_contents('11'))
        self.assertTrue(os.path.isdir(holder))
        self.assertTrue(os.path.isdir(other))

    def test_matches_json_style_superblock_format(self):
        # Tolerate the quoted-key format used by some kernels.
        self._add_client('7', '{"superblock":"fd:01:99","filename":"/x"}')

        expired = privsep_os._expire_nfs_clients_holding_dev(
            self.major, self.minor, self.clients_path)

        self.assertEqual(['7'], expired)

    def test_skips_clients_without_states_file(self):
        client_dir = os.path.join(self.clients_path, '3')
        os.makedirs(client_dir)

        expired = privsep_os._expire_nfs_clients_holding_dev(
            self.major, self.minor, self.clients_path)

        self.assertEqual([], expired)

    def test_missing_clients_path_returns_empty(self):
        expired = privsep_os._expire_nfs_clients_holding_dev(
            self.major, self.minor,
            os.path.join(self.clients_path, 'does-not-exist'))

        self.assertEqual([], expired)
