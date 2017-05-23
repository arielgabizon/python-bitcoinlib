# Copyright (C) 2007 Jan-Klaas Kollhof
# Copyright (C) 2011-2015 The python-bitcoinlib developers
# Copyright (C) 2017 The python-zcashlib developers
#
# This file is part of python-zcashlib.
#
# It is subject to the license terms in the LICENSE file found in the top-level
# directory of this distribution.
#
# No part of python-zcashlib, including this file, may be copied, modified,
# propagated, or distributed except according to the terms contained in the
# LICENSE file.

"""Zcash RPC support

By default this uses the standard library ``json`` module. By monkey patching,
a different implementation can be used instead, at your own risk:

>>> import simplejson
>>> import zcash.rpc
>>> zcash.rpc.json = simplejson

(``simplejson`` is the externally maintained version of the same module and
thus better optimized but perhaps less stable.)
"""

from __future__ import absolute_import, division, print_function, unicode_literals
import ssl

try:
    import http.client as httplib
except ImportError:
    import httplib
import base64
import binascii
import decimal
import json
import os
import platform
import sys
try:
    import urllib.parse as urlparse
except ImportError:
    import urlparse

import zcash
from zcash.core import COIN, x, lx, b2lx, CBlock, CBlockHeader, CTransaction, COutPoint, CTxOut
from zcash.core.script import CScript
from zcash.wallet import CBitcoinAddress, CBitcoinSecret

DEFAULT_USER_AGENT = "AuthServiceProxy/0.1"

DEFAULT_HTTP_TIMEOUT = 30

# (un)hexlify to/from unicode, needed for Python3
unhexlify = binascii.unhexlify
hexlify = binascii.hexlify
if sys.version > '3':
    unhexlify = lambda h: binascii.unhexlify(h.encode('utf8'))
    hexlify = lambda b: binascii.hexlify(b).decode('utf8')


class JSONRPCError(Exception):
    """JSON-RPC protocol error base class

    Subclasses of this class also exist for specific types of errors; the set
    of all subclasses is by no means complete.
    """

    SUBCLS_BY_CODE = {}

    @classmethod
    def _register_subcls(cls, subcls):
        cls.SUBCLS_BY_CODE[subcls.RPC_ERROR_CODE] = subcls
        return subcls

    def __new__(cls, rpc_error):
        assert cls is JSONRPCError
        cls = JSONRPCError.SUBCLS_BY_CODE.get(rpc_error['code'], cls)

        self = Exception.__new__(cls)

        super(JSONRPCError, self).__init__(
            'msg: %r  code: %r' %
            (rpc_error['message'], rpc_error['code']))
        self.error = rpc_error

        return self

@JSONRPCError._register_subcls
class ForbiddenBySafeModeError(JSONRPCError):
    RPC_ERROR_CODE = -2

@JSONRPCError._register_subcls
class InvalidAddressOrKeyError(JSONRPCError):
    RPC_ERROR_CODE = -5

@JSONRPCError._register_subcls
class InvalidParameterError(JSONRPCError):
    RPC_ERROR_CODE = -8

@JSONRPCError._register_subcls
class VerifyError(JSONRPCError):
    RPC_ERROR_CODE = -25

@JSONRPCError._register_subcls
class VerifyRejectedError(JSONRPCError):
    RPC_ERROR_CODE = -26

@JSONRPCError._register_subcls
class VerifyAlreadyInChainError(JSONRPCError):
    RPC_ERROR_CODE = -27

@JSONRPCError._register_subcls
class InWarmupError(JSONRPCError):
    RPC_ERROR_CODE = -28


class BaseProxy(object):
    """Base JSON-RPC proxy class. Contains only private methods; do not use
    directly."""

    def __init__(self,
                 service_url=None,
                 service_port=None,
                 zcash_conf_file=None,
                 timeout=DEFAULT_HTTP_TIMEOUT):

        # Create a dummy connection early on so if __init__() fails prior to
        # __conn being created __del__() can detect the condition and handle it
        # correctly.
        self.__conn = None
        #this line is only good for regtest
        service_port = 18232
        
        if service_url is None:
            # Figure out the path to the zcash.conf file
            if zcash_conf_file is None:
                if platform.system() == 'Windows':
                    zcash_conf_file = os.path.join(os.environ['APPDATA'], 'Zcash')
                else:
                    zcash_conf_file = os.path.expanduser('~/.zcash')
                zcash_conf_file = os.path.join(zcash_conf_file, 'zcash.conf')

            # Extract contents of zcash.conf to build service_url
            with open(zcash_conf_file, 'r') as fd:
                # zcash accepts empty rpcuser, not specified in zcash_conf_file
                conf = {'rpcuser': ""}
                for line in fd.readlines():
                    if '#' in line:
                        line = line[:line.index('#')]
                    if '=' not in line:
                        continue
                    k, v = line.split('=', 1)
                    conf[k.strip()] = v.strip()

                if service_port is None:
                    service_port = zcash.params.RPC_PORT
                conf['rpcport'] = int(conf.get('rpcport', service_port))
                conf['rpchost'] = conf.get('rpcconnect', 'localhost')

                if 'rpcpassword' not in conf:
                    raise ValueError('The value of rpcpassword not specified in the configuration file: %s' % zcash_conf_file)

                service_url = ('%s://%s:%s@%s:%d' %
                    ('http',
                     conf['rpcuser'], conf['rpcpassword'],
                     conf['rpchost'], conf['rpcport']))

        self.__service_url = service_url
        self.__url = urlparse.urlparse(service_url)
        print('url ', self.__url)
        if self.__url.scheme not in ('http',):
            raise ValueError('Unsupported URL scheme %r' % self.__url.scheme)
        print('Just before if clause:',self.__url.port)
        if self.__url.port is None:
            port = httplib.HTTP_PORT
            print('port line 174:', port)
        else:
            port = self.__url.port
            print("port line 174 else clause:", port)
        self.__id_count = 0
        authpair = "%s:%s" % (self.__url.username, self.__url.password)
        authpair = authpair.encode('utf8')
        self.__auth_header = b"Basic " + base64.b64encode(authpair)

        self.__conn = httplib.HTTPConnection(self.__url.hostname, port=port,
                                             timeout=timeout)


    def _call(self, service_name, *args):
        self.__id_count += 1

        postdata = json.dumps({'version': '1.1',
                               'method': service_name,
                               'params': args,
                               'id': self.__id_count})
        self.__conn.request('POST', self.__url.path, postdata,
                            {'Host': self.__url.hostname,
                             'User-Agent': DEFAULT_USER_AGENT,
                             'Authorization': self.__auth_header,
                             'Content-type': 'application/json'})

        response = self._get_response()
        if response['error'] is not None:
            raise JSONRPCError(response['error'])
        elif 'result' not in response:
            raise JSONRPCError({
                'code': -343, 'message': 'missing JSON-RPC result'})
        else:
            return response['result']


    def _batch(self, rpc_call_list):
        postdata = json.dumps(list(rpc_call_list))
        self.__conn.request('POST', self.__url.path, postdata,
                            {'Host': self.__url.hostname,
                             'User-Agent': DEFAULT_USER_AGENT,
                             'Authorization': self.__auth_header,
                             'Content-type': 'application/json'})

        return self._get_response()

    def _get_response(self):
        http_response = self.__conn.getresponse()
        if http_response is None:
            raise JSONRPCError({
                'code': -342, 'message': 'missing HTTP response from server'})

        return json.loads(http_response.read().decode('utf8'),
                          parse_float=decimal.Decimal)

    def __del__(self):
        if self.__conn is not None:
            self.__conn.close()


class RawProxy(BaseProxy):
    """Low-level proxy to a zcash JSON-RPC service

    Unlike ``Proxy``, no conversion is done besides parsing JSON. As far as
    Python is concerned, you can call any method; ``JSONRPCError`` will be
    raised if the server does not recognize it.
    """
    def __init__(self,
                 service_url=None,
                 service_port=None,
                 zcash_conf_file=None,
                 timeout=DEFAULT_HTTP_TIMEOUT,
                 **kwargs):
        super(RawProxy, self).__init__(service_url=service_url,
                                       service_port=service_port,
                                       zcash_conf_file=zcash_conf_file,
                                       timeout=timeout,
                                       **kwargs)

    def __getattr__(self, name):
        if name.startswith('__') and name.endswith('__'):
            # Python internal stuff
            raise AttributeError

        # Create a callable to do the actual call
        f = lambda *args: self._call(name, *args)

        # Make debuggers show <function zcash.rpc.name> rather than <function
        # zcash.rpc.<lambda>>
        f.__name__ = name
        return f


class Proxy(BaseProxy):
    """Proxy to a zcash RPC service

    Unlike ``RawProxy``, data is passed as ``zcash.core`` objects or packed
    bytes, rather than JSON or hex strings. Not all methods are implemented
    yet; you can use ``call`` to access missing ones in a forward-compatible
    way. Assumes Zcash version >= v1.0.0
    """

    def __init__(self,
                 service_url=None,
                 service_port=None,
                 zcash_conf_file=None,
                 timeout=DEFAULT_HTTP_TIMEOUT,
                 **kwargs):
        """Create a proxy object

        If ``service_url`` is not specified, the username and password are read
        out of the file ``zcash_conf_file``. If ``zcash_conf_file`` is not
        specified, ``~/.zcash/zcash.conf`` or equivalent is used by
        default.  The default port is set according to the chain parameters in
        use: mainnet, testnet, or regtest.

        Usually no arguments to ``Proxy()`` are needed; the local zcashd will
        be used.

        ``timeout`` - timeout in seconds before the HTTP interface times out
        """

        super(Proxy, self).__init__(service_url=service_url,
                                    service_port=service_port,
                                    zcash_conf_file=zcash_conf_file,
                                    timeout=timeout,
                                    **kwargs)

    def call(self, service_name, *args):
        """Call an RPC method by name and raw (JSON encodable) arguments"""
        return self._call(service_name, *args)

    def dumpprivkey(self, addr):
        """Return the private key matching an address
        """
        r = self._call('dumpprivkey', str(addr))
        return CBitcoinSecret(r)

    def fundrawtransaction(self, tx, include_watching=False):
        """Add inputs to a transaction until it has enough in value to meet its out value.

        include_watching - Also select inputs which are watch only

        Returns dict:

        {'tx':        Resulting tx,
         'fee':       Fee the resulting transaction pays,
         'changepos': Position of added change output, or -1,
        }
        """
        hextx = hexlify(tx.serialize())
        r = self._call('fundrawtransaction', hextx, include_watching)

        r['tx'] = CTransaction.deserialize(unhexlify(r['hex']))
        del r['hex']

        r['fee'] = int(r['fee'] * COIN)

        return r

    def generate(self, numblocks):
        """Mine blocks immediately (before the RPC call returns)

        numblocks - How many blocks are generated immediately.

        Returns iterable of block hashes generated.
        """
        r = self._call('generate', numblocks)
        return (lx(blk_hash) for blk_hash in r)

    def getaccountaddress(self, account=None):
        """Return the current zcash address for receiving payments to this
        account."""
        r = self._call('getaccountaddress', account)
        return CBitcoinAddress(r)

    def getbalance(self, account='*', minconf=1):
        """Get the balance

        account - The selected account. Defaults to "*" for entire wallet. It
        may be the default account using "".

        minconf - Only include transactions confirmed at least this many times.
        (default=1)
        """
        r = self._call('getbalance', account, minconf)
        return int(r*COIN)

    def getbestblockhash(self):
        """Return hash of best (tip) block in longest block chain."""
        return lx(self._call('getbestblockhash'))

    def getblockheader(self, block_hash, verbose=False):
        """Get block header <block_hash>

        verbose - If true a dict is returned with the values returned by
                  getblockheader that are not in the block header itself
                  (height, nextblockhash, etc.)

        Raises IndexError if block_hash is not valid.
        """
        try:
            block_hash = b2lx(block_hash)
        except TypeError:
            raise TypeError('%s.getblockheader(): block_hash must be bytes; got %r instance' %
                    (self.__class__.__name__, block_hash.__class__))
        try:
            r = self._call('getblockheader', block_hash, verbose)
        except InvalidAddressOrKeyError as ex:
            raise IndexError('%s.getblockheader(): %s (%d)' %
                    (self.__class__.__name__, ex.error['message'], ex.error['code']))

        if verbose:
            nextblockhash = None
            if 'nextblockhash' in r:
                nextblockhash = lx(r['nextblockhash'])
            return {'confirmations':r['confirmations'],
                    'height':r['height'],
                    'mediantime':r['mediantime'],
                    'nextblockhash':nextblockhash,
                    'chainwork':x(r['chainwork'])}
        else:
            return CBlockHeader.deserialize(unhexlify(r))


    def getblock(self, block_hash):
        """Get block <block_hash>

        Raises IndexError if block_hash is not valid.
        """
        try:
            block_hash = b2lx(block_hash)
        except TypeError:
            raise TypeError('%s.getblock(): block_hash must be bytes; got %r instance' %
                    (self.__class__.__name__, block_hash.__class__))
        try:
            r = self._call('getblock', block_hash, False)
        except InvalidAddressOrKeyError as ex:
            raise IndexError('%s.getblock(): %s (%d)' %
                    (self.__class__.__name__, ex.error['message'], ex.error['code']))
        return CBlock.deserialize(unhexlify(r))

    def getblockcount(self):
        """Return the number of blocks in the longest block chain"""
        return self._call('getblockcount')

    def getblockhash(self, height):
        """Return hash of block in best-block-chain at height.

        Raises IndexError if height is not valid.
        """
        try:
            return lx(self._call('getblockhash', height))
        except InvalidParameterError as ex:
            raise IndexError('%s.getblockhash(): %s (%d)' %
                    (self.__class__.__name__, ex.error['message'], ex.error['code']))

    def getinfo(self):
        """Return a JSON object containing various state info"""
        r = self._call('getinfo')
        if 'balance' in r:
            r['balance'] = int(r['balance'] * COIN)
        if 'paytxfee' in r:
            r['paytxfee'] = int(r['paytxfee'] * COIN)
        return r

    def getmininginfo(self):
        """Return a JSON object containing mining-related information"""
        return self._call('getmininginfo')

    def getnewaddress(self, account=None):
        """Return a new zcash address for receiving payments.

        If account is not None, it is added to the address book so payments
        received with the address will be credited to account.
        """
        r = None
        if account is not None:
            r = self._call('getnewaddress', account)
        else:
            r = self._call('getnewaddress')

        return CBitcoinAddress(r)

    def getrawchangeaddress(self):
        """Returns a new zcash address, for receiving change.

        This is for use with raw transactions, NOT normal use.
        """
        r = self._call('getrawchangeaddress')
        return CBitcoinAddress(r)

    def getrawmempool(self, verbose=False):
        """Return the mempool"""
        if verbose:
            return self._call('getrawmempool', verbose)

        else:
            r = self._call('getrawmempool')
            r = [lx(txid) for txid in r]
            return r

    def getrawtransaction(self, txid, verbose=False):
        """Return transaction with hash txid

        Raises IndexError if transaction not found.

        verbose - If true a dict is returned instead with additional
        information on the transaction.

        Note that if all txouts are spent and the transaction index is not
        enabled the transaction may not be available.
        """
        try:
            r = self._call('getrawtransaction', b2lx(txid), 1 if verbose else 0)
        except InvalidAddressOrKeyError as ex:
            raise IndexError('%s.getrawtransaction(): %s (%d)' %
                    (self.__class__.__name__, ex.error['message'], ex.error['code']))
        if verbose:
            r['tx'] = CTransaction.deserialize(unhexlify(r['hex']))
            r['hex']
            del r['txid']
            del r['version']
            del r['locktime']
            del r['vin']
            del r['vout']
            r['blockhash'] = lx(r['blockhash']) if 'blockhash' in r else None
        else:
            r = CTransaction.deserialize(unhexlify(r))

        return r

    def getreceivedbyaddress(self, addr, minconf=1):
        """Return total amount received by given a (wallet) address

        Get the amount received by <address> in transactions with at least
        [minconf] confirmations.

        Works only for addresses in the local wallet; other addresses will
        always show zero.

        addr    - The address. (CBitcoinAddress instance)

        minconf - Only include transactions confirmed at least this many times.
        (default=1)
        """
        r = self._call('getreceivedbyaddress', str(addr), minconf)
        return int(r * COIN)

    def gettransaction(self, txid):
        """Get detailed information about in-wallet transaction txid

        Raises IndexError if transaction not found in the wallet.

        FIXME: Returned data types are not yet converted.
        """
        try:
            r = self._call('gettransaction', b2lx(txid))
        except InvalidAddressOrKeyError as ex:
            raise IndexError('%s.getrawtransaction(): %s (%d)' %
                    (self.__class__.__name__, ex.error['message'], ex.error['code']))
        return r

    def gettxout(self, outpoint, includemempool=True):
        """Return details about an unspent transaction output.

        Raises IndexError if outpoint is not found or was spent.

        includemempool - Include mempool txouts
        """
        r = self._call('gettxout', b2lx(outpoint.hash), outpoint.n, includemempool)

        if r is None:
            raise IndexError('%s.gettxout(): unspent txout %r not found' % (self.__class__.__name__, outpoint))

        r['txout'] = CTxOut(int(r['value'] * COIN),
                            CScript(unhexlify(r['scriptPubKey']['hex'])))
        del r['value']
        del r['scriptPubKey']
        r['bestblock'] = lx(r['bestblock'])
        return r

    def importaddress(self, addr, label='', rescan=True):
        """Adds an address or pubkey to wallet without the associated privkey."""
        addr = str(addr)

        r = self._call('importaddress', addr, label, rescan)
        return r

    def listreceivedbyaddress(self, minconf=1):
        r = self._call('listreceivedbyaddress',minconf,False)
        return r
    
    def listtransactions(self):
        r = self._call('listtransactions')
        return r
      
    def listunspent(self, minconf=0, maxconf=9999999, addrs=None):
        """Return unspent transaction outputs in wallet

        Outputs will have between minconf and maxconf (inclusive)
        confirmations, optionally filtered to only include txouts paid to
        addresses in addrs.
        """
        r = None
        if addrs is None:
            r = self._call('listunspent', minconf, maxconf)
        else:
            addrs = [str(addr) for addr in addrs]
            r = self._call('listunspent', minconf, maxconf, addrs)

        r2 = []
        for unspent in r:
            unspent['outpoint'] = COutPoint(lx(unspent['txid']), unspent['vout'])
            
            unspent['address'] = CBitcoinAddress(unspent['address'])
            unspent['scriptPubKey'] = CScript(unhexlify(unspent['scriptPubKey']))
            unspent['amount'] = int(unspent['amount'] * COIN)
            r2.append(unspent)
        return r2

    def lockunspent(self, unlock, outpoints):
        """Lock or unlock outpoints"""
        json_outpoints = [{'txid':b2lx(outpoint.hash), 'vout':outpoint.n}
                          for outpoint in outpoints]
        return self._call('lockunspent', unlock, json_outpoints)

    def sendrawtransaction(self, tx, allowhighfees=False):
        """Submit transaction to local node and network.

        allowhighfees - Allow even if fees are unreasonably high.
        """
        hextx = hexlify(tx.serialize())
        r = None
        if allowhighfees:
            r = self._call('sendrawtransaction', hextx, True)
        else:
            r = self._call('sendrawtransaction', hextx)
        return lx(r)

    def sendmany(self, fromaccount, payments, minconf=1, comment='', subtractfeefromamount=[]):
        """Send amount to given addresses.

        payments - dict with {address: amount}
        """
        json_payments = {str(addr):float(amount)/COIN
                         for addr, amount in payments.items()}
        r = self._call('sendmany', fromaccount, json_payments, minconf, comment, subtractfeefromamount)
        return lx(r)

    def sendtoaddress(self, addr, amount, comment='', commentto='', subtractfeefromamount=False):
        """Send amount to a given address"""
        addr = str(addr)
        amount = float(amount)/COIN
        r = self._call('sendtoaddress', addr, amount, comment, commentto, subtractfeefromamount)
        return lx(r)

    def signrawtransaction(self, tx, *args):
        """Sign inputs for transaction

        FIXME: implement options
        """
        hextx = hexlify(tx.serialize())
        r = self._call('signrawtransaction', hextx, *args)
        r['tx'] = CTransaction.deserialize(unhexlify(r['hex']))
        del r['hex']
        return r

    def submitblock(self, block, params=None):
        """Submit a new block to the network.

        params is optional and is currently ignored by bitcoind. See
        https://en.zcash.it/wiki/BIP_0022 for full specification.
        """
        hexblock = hexlify(block.serialize())
        if params is not None:
            return self._call('submitblock', hexblock, params)
        else:
            return self._call('submitblock', hexblock)

    def validateaddress(self, address):
        """Return information about an address"""
        r = self._call('validateaddress', str(address))
        if r['isvalid']:
            r['address'] = CBitcoinAddress(r['address'])
        if 'pubkey' in r:
            r['pubkey'] = unhexlify(r['pubkey'])
        return r

    def unlockwallet(self, password, timeout=60):
        """Stores the wallet decryption key in memory for 'timeout' seconds.

        password - The wallet passphrase.

        timeout - The time to keep the decryption key in seconds.
        (default=60)
        """
        r = self._call('walletpassphrase', password, timeout)
        return r

    ### Z-address methods below

    def z_exportkey(zaddr):
        """Reveals the zkey corresponding to 'zaddr'.
        Then the z_importkey can be used with this output
        """
        r = self._call('z_exportkey', zaddr)
        return r

    def z_exportwallet(filename):
        """Exports all wallet keys, for taddr and zaddr, in a human-readable format."""
        r = self._call('z_exportwallet', filename)
        return r

    def z_getbalance(zaddr, minconf=1):
        """Returns the balance of a taddr or zaddr belonging to the node’s wallet."""
        return self._call('z_getbalance', minconf)

    def z_getnewaddress(self):
        """Returns a new zaddr for receiving payments."""
        r = self._call('z_getnewaddress')
        return r

    def z_getoperationresult(self, opid):
        """Retrieve the result and status of an operation which has finished, and then remove the operation from memory.
        opid - (array, optional) A list of operation ids we are interested in.
        If not provided, examine all operations known to the node.
        """
        return self._call('z_getoperationresult')

    def z_getoperationstatus(self, opid):
        """Get operation status and any associated result or error data.  The operation will remain in memory.
        opid - (array, optional) A list of operation ids we are interested in.
        If not provided, examine all operations known to the node.
        """
        return self._call('z_getoperationstatus')

    def z_gettotalbalance(self, minconf=1):
        """Return the total value of funds stored in the node’s wallet."""
        return self._call('z_gettotalbalance', minconf)

    def z_importkey(zkey, rescan='whenkeyisnew', startHeight=0):
        """Adds a zkey (as returned by z_exportkey) to your wallet.
        1. "zkey"             (string, required) The zkey (see z_exportkey)
        2. rescan             (string, optional, default="whenkeyisnew") Rescan the wallet for transactions - can be "yes", "no" or "whenkeyisnew"
        3. startHeight        (numeric, optional, default=0) Block height to start rescan from
        Note: This call can take minutes to complete if rescan is true."""
        r = self._call('z_importkey', zkey, rescan, startHeight)
        return r

    def z_importwallet(filename):
        """Imports taddr and zaddr keys from a wallet export file (see z_exportwallet).
        filename - The wallet file
        """
        r = self._call('z_importwallet', filename)
        return r

    def z_listaddresses(self):
        """Returns the list of zaddr belonging to the wallet."""
        return self._call('z_listaddresses')

    def z_listoperationids():
        """Returns the list of operation ids currently known to the wallet.
        status - (string, optional) Filter result by the operation's state state e.g. "success".
        """
        return self._call('z_listoperationids')

    def z_listreceivedbyaddress(self, zaddr, minconf=1):
        """Return a list of amounts received by a zaddr belonging to the node’s wallet."""
        r = self._call('z_listreceivedbyaddress', str(zaddr), minconf)
        return r

    def z_sendmany(self, fromaddress, amounts, minconf=1, fee=0.0001):
        """Send multiple times. Amounts are double-precision floating point numbers.
        Change from a taddr flows to a new taddr address, while change from zaddr returns to itself.
        When sending coinbase UTXOs to a zaddr, change is not allowed. The entire value of the UTXO(s) must be consumed.
        Currently, the maximum number of zaddr outputs is 54 due to transaction size limits.
        1. "fromaddress"         (string, required) The taddr or zaddr to send the funds from.
        2. "amounts"             (array, required) An array of json objects representing the amounts to send.
            [{
              "address":address  (string, required) The address is a taddr or zaddr
              "amount":amount    (numeric, required) The numeric amount in ZEC is the value
              "memo":memo        (string, optional) If the address is a zaddr, raw data represented in hexadecimal string format
            }, ... ]
        3. minconf               (numeric, optional, default=1) Only use funds confirmed at least this many times.
        4. fee                   (numeric, optional, default=0.0001) The fee amount to attach to this transaction.
        """
        r = self._call('z_sendmany', fromaddress, amounts, minconf, fee)
        return r

    def decoderawtransaction(self, txhex):
        """Return a JSON object representing the serialized, hex-encoded transaction."""
        return self._call('decoderawtransaction', txhex)

    # Nodes
    def _addnode(self, node, arg):
        r = self._call('addnode', node, arg)
        return r

    def addnode(self, node):
        return self._addnode(node, 'add')

    def addnodeonetry(self, node):
        return self._addnode(node, 'onetry')

    def removenode(self, node):
        return self._addnode(node, 'remove')


__all__ = (
    'JSONRPCError',
    'ForbiddenBySafeModeError',
    'InvalidAddressOrKeyError',
    'InvalidParameterError',
    'VerifyError',
    'VerifyRejectedError',
    'VerifyAlreadyInChainError',
    'InWarmupError',
    'RawProxy',
    'Proxy',
)
