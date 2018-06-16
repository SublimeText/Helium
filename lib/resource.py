'''Module mimicing the standard `resource` module.

ST3's internal Python interpreter does not include `resource` module,
but `ptyprocess` module depends on it.
This module includes the functions used by `ptyprocess` module.

This is not used on Windows.
`paramiko` module, which is not dependent on `resource` module, is used instead.
'''

import subprocess


RLIMIT_NOFILE = 1


def getrlimit(resource):
    if resource == RLIMIT_NOFILE:
        soft_limit = int(subprocess.check_output(['ulimit', '-Sn']))
        # Hard limit is not used by `pexpect` anyway.
        hard_limit = subprocess.check_output(['ulimit', '-Sn'])
        hard_limit = int(hard_limit) if hard_limit != 'unlimited' else float('inf')
        return (soft_limit, hard_limit)
