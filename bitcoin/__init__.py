# Copyright (C) 2012-2016 The python-bitcoinlib developers
#
# This file is part of python-bitcoinlib.
#
# It is subject to the license terms in the LICENSE file found in the top-level
# directory of this distribution.
#
# No part of python-bitcoinlib, including this file, may be copied, modified,
# propagated, or distributed except according to the terms contained in the
# LICENSE file.

from __future__ import absolute_import, division, print_function, unicode_literals

import bitcoin.core

# Note that setup.py can break if __init__.py imports any external
# dependencies, as these might not be installed when setup.py runs. In this
# case __version__ could be moved to a separate version.py and imported here.
__version__ = '0.7.1-SNAPSHOT'

class MainParams(bitcoin.core.CoreMainParams):
    MESSAGE_START = b'\x24\xe9\x27\x64'
    DEFAULT_PORT = 8233
    RPC_PORT = 8232
    DNS_SEEDS = (('z.cash', 'dnsseed.z.cash'),
                 ('str4d.xyz', 'dnsseed.str4d.xyz'),
                 ('znodes.org', 'dnsseed.znodes.org'))
    BASE58_PREFIXES = {'PUBKEY_ADDR':b'\x1c\xb8',
                       'SCRIPT_ADDR':b'\x1c\xbd',
                       'SECRET_KEY' :128}
    # BASE58_PREFIXES = {'PUBKEY_ADDR':7352,
    #                    'SCRIPT_ADDR':7357,
    #                    'SECRET_KEY' :128}


class TestNetParams(bitcoin.core.CoreTestNetParams):
    MESSAGE_START = b'\xfa\x1a\xf9\xbf'
    DEFAULT_PORT = 18233
    RPC_PORT = 18232
    DNS_SEEDS = (('z.cash', 'dnsseed.testnet.z.cash'))
    BASE58_PREFIXES = {'PUBKEY_ADDR':b'\x1d\x25',
                       'SCRIPT_ADDR':b'\x1c\xba',
                       'SECRET_KEY' :239}
    # BASE58_PREFIXES = {'PUBKEY_ADDR':7461,
    #                    'SCRIPT_ADDR':7354,
    #                    'SECRET_KEY' :239}

class RegTestParams(bitcoin.core.CoreRegTestParams):
    MESSAGE_START = b'\xaa\xea\x3f\x5f'
    DEFAULT_PORT = 18444
    RPC_PORT = 18232
    DNS_SEEDS = ()
    BASE58_PREFIXES = {'PUBKEY_ADDR':7461,
                       'SCRIPT_ADDR':7354,
                       'SECRET_KEY' :239}

"""Master global setting for what chain params we're using.

However, don't set this directly, use SelectParams() instead so as to set the
bitcoin.core.params correctly too.
"""
#params = bitcoin.core.coreparams = MainParams()
params = MainParams()

def SelectParams(name):
    """Select the chain parameters to use

    name is one of 'mainnet', 'testnet', or 'regtest'

    Default chain is 'mainnet'
    """
    global params
    bitcoin.core._SelectCoreParams(name)
    if name == 'mainnet':
        params = bitcoin.core.coreparams = MainParams()
    elif name == 'testnet':
        params = bitcoin.core.coreparams = TestNetParams()
    elif name == 'regtest':
        params = bitcoin.core.coreparams = RegTestParams()
    else:
        raise ValueError('Unknown chain %r' % name)
