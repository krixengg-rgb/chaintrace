"""EVM chain configs (pure data). ChainTrace treats Ethereum, BNB Smart Chain, Arbitrum One, Base, Polygon PoS and OP Mainnet
through one code path; everything chain-specific lives here. All endpoints are free and keyless.
History sources, in order: the chain's public Blockscout API -> (optional) Blockscout multichain API with BLOCKSCOUT_API_KEY ->
the keyless fallback (Ethplorer / Binplorer, or a recent-window RPC log scan of major tokens)."""
import os
BS_KEY = (os.environ.get("BLOCKSCOUT_API_KEY") or "").strip() or None
EVM = {
 "eth": {"name": "Ethereum", "short": "ETH", "id": 1, "unit": "ETH", "color": "#8c9eff",
         "bs": [os.environ.get("CHAINTRACE_BS", "https://eth.blockscout.com/api/v2")],
         "rpcs": ["https://ethereum-rpc.publicnode.com", "https://eth.drpc.org", "https://cloudflare-eth.com"],
         "fallback": "ethplorer", "ex": "https://etherscan.io", "wnative": "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2"},
 "bsc": {"name": "BNB Smart Chain", "short": "BSC", "id": 56, "unit": "BNB", "color": "#f3ba2f",
         "bs": [],   # no public Blockscout for BSC; Binplorer (Ethplorer's BSC twin, public 'freekey') is the history source
         "rpcs": ["https://bsc-rpc.publicnode.com", "https://bsc-dataseed.bnbchain.org", "https://bsc-dataseed1.defibit.io"],
         "fallback": "binplorer", "ex": "https://bscscan.com", "wnative": "0xbb4cdb9cbd36b01bd1cbaebf2de08d9173bc095c",
         "logs": {"rpc": "https://bsc-rpc.publicnode.com", "span": 49000, "windows": 3}},
 "arb": {"name": "Arbitrum One", "short": "ARB", "id": 42161, "unit": "ETH", "color": "#28a0f0",
         "bs": ["https://arbitrum.blockscout.com/api/v2"],
         "rpcs": ["https://arb1.arbitrum.io/rpc", "https://arbitrum-one-rpc.publicnode.com", "https://arbitrum.drpc.org"],
         "fallback": "logs", "ex": "https://arbiscan.io", "wnative": "0x82af49447d8a07e3bd95bd0d56f35241523fbab1",
         "logs": {"rpc": "https://arb1.arbitrum.io/rpc", "span": 29000, "windows": 4}},
 "base": {"name": "Base", "short": "BASE", "id": 8453, "unit": "ETH", "color": "#0052ff",
          "bs": ["https://base.blockscout.com/api/v2"],
          "rpcs": ["https://base-rpc.publicnode.com", "https://mainnet.base.org", "https://base.drpc.org"],
          "fallback": "logs", "ex": "https://basescan.org", "wnative": "0x4200000000000000000000000000000000000006",
          "logs": {"rpc": "https://base-rpc.publicnode.com", "span": 49000, "windows": 3}},
 "polygon": {"name": "Polygon PoS", "short": "POL", "id": 137, "unit": "POL", "color": "#8247e5",
             "bs": ["https://polygon.blockscout.com/api/v2"],
             "rpcs": ["https://polygon-bor-rpc.publicnode.com", "https://polygon.drpc.org"],
             "fallback": "logs", "ex": "https://polygonscan.com", "wnative": "0x0d500b1d8e8ef31e21c99d1db9a6444d3adf1270",
             "logs": {"rpc": "https://polygon-bor-rpc.publicnode.com", "span": 9900, "windows": 6}},
 "op": {"name": "OP Mainnet", "short": "OP", "id": 10, "unit": "ETH", "color": "#ff0420",
        "bs": ["https://explorer.optimism.io/api/v2"],
        "rpcs": ["https://optimism-rpc.publicnode.com", "https://mainnet.optimism.io", "https://optimism.drpc.org"],
        "fallback": "logs", "ex": "https://optimistic.etherscan.io", "wnative": "0x4200000000000000000000000000000000000006",
        "logs": {"rpc": "https://mainnet.optimism.io", "span": 9900, "windows": 4}},
}
EVM_CHAINS = tuple(EVM)
NEW = tuple(c for c in EVM if c != "eth")   # chains whose graph node ids are chain-prefixed ("base:0x…"); Ethereum keeps bare ids
for c, v in EVM.items():
    v["tx"] = v["ex"] + "/tx/"; v["ad"] = v["ex"] + "/address/"
    if BS_KEY: v["bs"] = v["bs"] + [f"https://api.blockscout.com/{v['id']}/api/v2"]
# major tokens per chain (verified on-chain with symbol()); used by the RPC log-scan fallback and to skip eth_calls
TOKENS = {
 "bsc": {"0x55d398326f99059ff775485246999027b3197955": ("USDT", 18), "0x8ac76a51cc950d9822d68b83fe1ad97b32cd580d": ("USDC", 18),
         "0xbb4cdb9cbd36b01bd1cbaebf2de08d9173bc095c": ("WBNB", 18), "0xe9e7cea3dedca5984780bafc599bd69add087d56": ("BUSD", 18),
         "0x2170ed0880ac9a755fd29b2688956bd959f933f8": ("ETH", 18), "0x7130d2a12b9bcbfae4f2634d864a1ee1ce3ead9c": ("BTCB", 18),
         "0xc5f0f7b66764f6ec8c8dff7ba683102295e16409": ("FDUSD", 18)},
 "arb": {"0xaf88d065e77c8cc2239327c5edb3a432268e5831": ("USDC", 6), "0xff970a61a04b1ca14834a43f5de4533ebddb5cc8": ("USDC.e", 6),
         "0xfd086bc7cd5c481dcc9c85ebe478a1c0b69fcbb9": ("USDT0", 6), "0x82af49447d8a07e3bd95bd0d56f35241523fbab1": ("WETH", 18),
         "0x912ce59144191c1204e64559fe8253a0e49e6548": ("ARB", 18), "0x2f2a2543b76a4166549f7aab2e75bef0aefc5b0f": ("WBTC", 8),
         "0xda10009cbd5d07dd0cecc66161fc93d7c9000da1": ("DAI", 18)},
 "base": {"0x833589fcd6edb6e08f4c7c32d4f71b54bda02913": ("USDC", 6), "0x4200000000000000000000000000000000000006": ("WETH", 18),
          "0xd9aaec86b65d86f6a7b5b1b0c42ffa531710b6ca": ("USDbC", 6), "0x50c5725949a6f0c72e6c4a641f24049a917db0cb": ("DAI", 18),
          "0xcbb7c0000ab88b473b1f5afd9ef808440eed33bf": ("cbBTC", 8), "0xfde4c96c8593536e31f229ea8f37b2ada2699bb2": ("USDT", 6),
          "0x940181a94a35a4569e4529a3cdfb74e38fd98631": ("AERO", 18)},
 "polygon": {"0x3c499c542cef5e3811e1192ce70d8cc03d5c3359": ("USDC", 6), "0x2791bca1f2de4661ed88a30c99a7a9449aa84174": ("USDC.e", 6),
             "0xc2132d05d31c914a87c6611c10748aeb04b58e8f": ("USDT0", 6), "0x7ceb23fd6bc0add59e62ac25578270cff1b9f619": ("WETH", 18),
             "0x0d500b1d8e8ef31e21c99d1db9a6444d3adf1270": ("WPOL", 18), "0x1bfd67037b42cf73acf2047067bd4f2c47d9bfd6": ("WBTC", 8),
             "0x8f3cf7ad23cd3cadbd9735aff958023239c6a063": ("DAI", 18)},
 "op": {"0x0b2c639c533813f4aa9d7837caf62653d097ff85": ("USDC", 6), "0x7f5c764cbc14f9669b88837ca1490cca17c31607": ("USDC.e", 6),
        "0x94b008aa00579c1307b0ef2c499ad98a8ce58e58": ("USDT", 6), "0x4200000000000000000000000000000000000006": ("WETH", 18),
        "0x4200000000000000000000000000000000000042": ("OP", 18), "0xda10009cbd5d07dd0cecc66161fc93d7c9000da1": ("DAI", 18),
        "0x68f180fcce6836688e9084f035309e29bf0a2095": ("WBTC", 8)},
}
# Polygon PoS native POL transfers are mirrored as LogTransfer events by the system contract 0x…1010 (lets the log scan see native moves)
POLYGON_MRC20 = "0x0000000000000000000000000000000000001010"
T_LOGTRANSFER = "0xe6497e3ee548a3372136af2fcb0696db31fc6cf20260707645068bd3fe97f3c4"
# DEX factories per chain (pool.factory() -> name). Checked to hold code on-chain.
FACTORIES = {
 "bsc": {"0xca143ce32fe78f1f7019d7d551a6402fc5350c73": "PancakeSwap V2", "0x0bfbcf9fa4f9c56b0f40a671ad40e0805a091865": "PancakeSwap V3",
         "0xdb1d10011ad0ff90774d0c6bb92e5c5c8b4461f7": "Uniswap V3", "0x8909dc15e40173ff4699343b6eb8132c65e18ec6": "Uniswap V2",
         "0x858e3312ed3a876947ea49d572a7c42de08af7ee": "Biswap"},
 "arb": {"0x1f98431c8ad98523631ae4a59f267346ea31f984": "Uniswap V3", "0xf1d7cc64fb4452f05c498126312ebe29f30fbcf9": "Uniswap V2",
         "0xc35dadb65012ec5796536bd9864ed8773abc74c4": "SushiSwap", "0x6eccab422d763ac031210895c81787e87b43a652": "Camelot V2",
         "0x1a3c9b1d2f0529d97f2afc5136cc23e58f1fd35b": "Camelot V3 (Algebra)", "0x0bfbcf9fa4f9c56b0f40a671ad40e0805a091865": "PancakeSwap V3"},
 "base": {"0x33128a8fc17869897dce68ed026d694621f6fdfd": "Uniswap V3", "0x8909dc15e40173ff4699343b6eb8132c65e18ec6": "Uniswap V2",
          "0x420dd381b31aef6683db6b902084cb0ffece40da": "Aerodrome", "0x5e7bb104d84c7cb9b682aac2f3d509f5f406809a": "Aerodrome Slipstream",
          "0x0bfbcf9fa4f9c56b0f40a671ad40e0805a091865": "PancakeSwap V3", "0xc35dadb65012ec5796536bd9864ed8773abc74c4": "SushiSwap"},
 "op": {"0x1f98431c8ad98523631ae4a59f267346ea31f984": "Uniswap V3", "0xf1046053aa5682b4f9a81b5481394da16be5ff5a": "Velodrome",
        "0xcc0bddb707055e04e497ab22a59c2af4391cd12f": "Velodrome Slipstream", "0x0c3c1c532f1e39edf36be9fe0be1410313e074bf": "Uniswap V2"},
 "polygon": {"0x1f98431c8ad98523631ae4a59f267346ea31f984": "Uniswap V3", "0x5757371414417b8c6caad45baef941abc7d3ab32": "QuickSwap V2",
             "0x411b0facc3489691f28ad58c47006af5e3ab3a28": "QuickSwap V3 (Algebra)", "0xc35dadb65012ec5796536bd9864ed8773abc74c4": "SushiSwap",
             "0x9e5a52f57b3038f1b8eee45f28b3c1967e22799c": "Uniswap V2"},
}
def nid(chain, a):
    """graph node id: Ethereum keeps the bare address; other EVM chains are prefixed (the same 0x address on two chains is two accounts)"""
    return a if chain not in NEW or not a or str(a).startswith(chain + ":") else f"{chain}:{a}"
def split(q):
    """'base:0xabc' -> ('base', '0xabc'); anything else -> (None, q)"""
    q = (q or "").strip()
    if ":" in q and not q.startswith("tx:"):
        c, a = q.split(":", 1)
        if c in EVM: return c, a
    return None, q
def bare(q): return split(q)[1]
