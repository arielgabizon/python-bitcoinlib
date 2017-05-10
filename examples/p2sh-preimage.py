#!/usr/bin/env python3

# Copyright (C) 2017 the python-zcashlib developers

import sys
if sys.version_info.major < 3:
    sys.stderr.write('Sorry, Python 3.x required by this example.\n')
    sys.exit(1)

import zcash
import zcash.rpc
from zcash import SelectParams
from zcash.core import b2x, lx, COIN, COutPoint, CMutableTxOut, CMutableTxIn, CMutableTransaction, Hash160
from zcash.core.script import CScript, OP_DUP, OP_HASH160, OP_SHA256, OP_EQUAL, OP_EQUALVERIFY, OP_CHECKSIG, SignatureHash, SIGHASH_ALL, SIGHASH_ANYONECANPAY
from zcash.core.scripteval import VerifyScript, SCRIPT_VERIFY_P2SH
from zcash.wallet import CBitcoinAddress, CBitcoinSecret

SelectParams('testnet')

import hashlib

proxy = zcash.rpc.Proxy()
info = proxy.getinfo()
print("INFO FROM PROXY: ", info)


# Create the (in)famous correct brainwallet secret key.
preimage = b'helloworld'
print('preimage to hex', b2x(preimage))
hashstring = hashlib.sha256(preimage).digest()
print('hashstring: ', b2x(hashstring))

# Create a redeemScript. Similar to a scriptPubKey the redeemScript must be
# satisfied for the funds to be spent.
txin_redeemScript = CScript([OP_SHA256, hashstring, OP_EQUAL])
print(b2x(txin_redeemScript))

# Create the magic P2SH scriptPubKey format from that redeemScript. You should
# look at the CScript.to_p2sh_scriptPubKey() function in zcash.core.script to
# understand what's happening, as well as read BIP16:
# https://github.com/bitcoin/bips/blob/master/bip-0016.mediawiki
txin_scriptPubKey = txin_redeemScript.to_p2sh_scriptPubKey()

# Convert the P2SH scriptPubKey to a base58 zcash address and print it.
# You'll need to send some funds to it to create a txout to spend.
txin_p2sh_address = CBitcoinAddress.from_scriptPubKey(txin_scriptPubKey)
print('Pay to:',str(txin_p2sh_address))

# Same as the txid:vout the createrawtransaction RPC call requires
#
# lx() takes *little-endian* hex and converts it to bytes; in Bitcoin
# transaction hashes are shown little-endian rather than the usual big-endian.
# There's also a corresponding x() convenience function that takes big-endian
# hex and converts it to bytes.
txid = lx('7064c9c78c4839c456ae13be70a184c0f773ec57c083a17ed18846be9072a61a')
vout = 1

# Create the txin structure, which includes the outpoint. The scriptSig
# defaults to being empty.
txin = CMutableTxIn(COutPoint(txid, vout))

# Create the txout. This time we create the scriptPubKey from a Bitcoin
# address.
txout = CMutableTxOut(1.10*COIN, CBitcoinAddress('tmQaM6Ry86vdrokJG8YbNqbouCQ6Kd71agZ').to_scriptPubKey())

# Create the unsigned transaction.
tx = CMutableTransaction([txin], [txout])

# Calculate the signature hash for that transaction. Note how the script we use
# is the redeemScript, not the scriptPubKey. That's because when the CHECKSIG
# operation happens EvalScript() will be evaluating the redeemScript, so the
# corresponding SignatureHash() function will use that same script when it
# replaces the scriptSig in the transaction being hashed with the script being
# executed.
sighash = SignatureHash(txin_redeemScript, tx, 0, SIGHASH_ANYONECANPAY)
print('sighash', b2x(sighash))

# privkey = CBitcoinSecret('cNUMK7zPWDq8YLFoARbLiFSgJnZ4jDuJzXxdSebNupzHB8ZSbQ4n')
# Now sign it. We have to append the type of signature we want to the end, in
# this case the usual SIGHASH_ALL.
# sig = privkey.sign(sighash) + bytes([SIGHASH_ANYONECANPAY])

# Set the scriptSig of our transaction input appropriately.
txin.scriptSig = CScript([preimage, txin_redeemScript])

print('tx', tx)
# Verify the signature worked. This calls EvalScript() and actually executes
# the opcodes in the scripts to see if everything worked out. If it doesn't an
# exception will be raised.
VerifyScript(txin.scriptSig, txin_scriptPubKey, tx, 0, (SCRIPT_VERIFY_P2SH,))

# Done! Print the transaction to standard output with the bytes-to-hex
# function.
print('Serialized txn', b2x(tx.serialize()))
