# Copyright 2021 Red Hat, Inc
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

"""
Helpers for os basic commands
"""

import os
import re

from oslo_concurrency import processutils
from oslo_log import log

from manila import exception

import manila.privsep

LOG = log.getLogger(__name__)


@manila.privsep.sys_admin_pctxt.entrypoint
def rmdir(dir_path):
    processutils.execute('rmdir', dir_path)


def _expire_nfs_clients_holding_dev(major, minor, clients_path):
    """Expire NFSv4 clients holding open state on the given device.

    Walks the kernel NFS server client list (``/proc/fs/nfsd/clients``) and,
    for every client that has open/lock state referencing the ``major:minor``
    device, writes ``expire`` to its ``ctl`` file to forcibly release that
    state. Returns the list of expired client ids.

    Pulled out of the privsep entrypoint so it can be unit tested without
    privsep.
    """
    expired = []
    # The kernel reports the device in the 'states' file as e.g.
    # superblock: "fd:01:1234" (major:minor:inode, all but the inode in hex).
    # Match leniently to tolerate format differences across kernels.
    superblock_re = re.compile(
        r'superblock"?\s*:\s*"%02x:%02x:' % (major, minor))
    try:
        client_ids = os.listdir(clients_path)
    except OSError:
        # NFS server not running, or the clients dir is not exposed (e.g. not
        # bind-mounted into a container). Nothing we can do; let the caller
        # fall back to retrying the unmount.
        return expired
    for client_id in client_ids:
        states_path = os.path.join(clients_path, client_id, 'states')
        try:
            with open(states_path) as f:
                states = f.read()
        except OSError:
            continue
        if not superblock_re.search(states):
            continue
        try:
            with open(os.path.join(clients_path, client_id, 'ctl'), 'w') as f:
                f.write('expire\n')
            expired.append(client_id)
        except OSError as e:
            LOG.warning("Failed to expire NFS client %(id)s: %(err)s",
                        {'id': client_id, 'err': e})
    return expired


@manila.privsep.sys_admin_pctxt.entrypoint
def expire_nfs_clients_holding_dev(major, minor,
                                   clients_path='/proc/fs/nfsd/clients'):
    """Expire NFSv4 client state pinning the given device.

    When an NFSv4 client (for example a now-deleted VM) mounts a share but
    never unmounts it, the kernel NFS server retains the client's open state,
    keeping the share filesystem busy and preventing it from being unmounted
    (the state is held as a 'courtesy' client for up to ~24h). Forcibly
    expire any client still referencing the share's device so the share can
    be torn down.
    """
    return _expire_nfs_clients_holding_dev(major, minor, clients_path)


@manila.privsep.sys_admin_pctxt.entrypoint
def mkdir(dir_path):
    processutils.execute('mkdir', dir_path)


@manila.privsep.sys_admin_pctxt.entrypoint
def recursive_forced_rm(dir_path):
    processutils.execute('rm', '-rf', dir_path)


@manila.privsep.sys_admin_pctxt.entrypoint
def is_data_definition_direct_io_supported(src_str, dest_str):
    try:
        processutils.execute(
            'dd', 'count=0', f'if={src_str}', f'of={dest_str}',
            'iflag=direct', 'oflag=direct')
        is_direct_io_supported = True
    except exception.ProcessExecutionError:
        is_direct_io_supported = False

    return is_direct_io_supported


@manila.privsep.sys_admin_pctxt.entrypoint
def data_definition(src_str, dest_str, size_in_g, use_direct_io=False):
    extra_flags = []
    if use_direct_io:
        extra_flags += ['iflag=direct', 'oflag=direct']
    processutils.execute(
        'dd', 'if=%s' % src_str, 'of=%s' % dest_str, 'count=%d' % size_in_g,
        'bs=1M', *extra_flags)


@manila.privsep.sys_admin_pctxt.entrypoint
def umount(mount_path):
    processutils.execute('umount', '-f', mount_path)


@manila.privsep.sys_admin_pctxt.entrypoint
def mount(device_name, mount_path, mount_type=None):
    extra_args = ['-t', mount_type] if mount_type else []
    processutils.execute('mount', device_name, mount_path, *extra_args)


@manila.privsep.sys_admin_pctxt.entrypoint
def list_mounts():
    out, err = processutils.execute('mount', '-l')
    return out, err


@manila.privsep.sys_admin_pctxt.entrypoint
def chmod(permission_level_str, mount_path):
    processutils.execute('chmod', permission_level_str, mount_path)


@manila.privsep.sys_admin_pctxt.entrypoint
def find(directory_to_find, min_depth='1', dirs_to_ignore=[], delete=False):
    ignored_dirs = []
    extra_args = []
    for dir in dirs_to_ignore:
        ignored_dirs += '!', '-path', dir

    if delete:
        extra_args.append('-delete')

    processutils.execute(
        'find', directory_to_find, '-mindepth', min_depth, *ignored_dirs,
        *extra_args)
