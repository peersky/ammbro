"""Curated retail router / frontend / settlement addresses (mainnet).

Benign-label source (§14.3): flow whose tx.to is a known retail router is
labeled benign. Identity-axis only — independent of price by construction.
Modeled on the orderflow.art "known routers by frontends" methodology.

Conservative by design: undercounts retail (unlabeled small routers) →
Study A AUC reads as a lower bound. Never add searcher-operated
contracts here.
"""

ROUTERS: dict[str, str] = {
    # Uniswap
    "0xe592427a0aece92de3edee1f18e0157c05861564": "uniswap_v3_swaprouter",
    "0x68b3465833fb72a70ecdf485e0e4c7bd8665fc45": "uniswap_v3_swaprouter02",
    "0x3fc91a3afd70395cd496c647d5a6cc9d4b2b7fad": "uniswap_universal_router",
    "0x66a9893cc07d91d95644aedd05d03f95e1dba8af": "uniswap_universal_router_v2",
    # UniswapX reactors
    "0x00000011f84b9aa48e5f8aa8b9897600006289be": "uniswapx_dutch_v1",
    "0x6000da47483062a0d734ba3dc7576ce6a0b645c4": "uniswapx_dutch_v2",
    # 1inch
    "0x1111111254eeb25477b68fb85ed929f73a960582": "1inch_v5",
    "0x111111125421ca6dc452d289314280a0f8842a65": "1inch_v6",
    # MetaMask
    "0x881d40237659c251811cec9c364ef91dc08d300c": "metamask_swap",
    # 0x
    "0xdef1c0ded9bec7f1a1670819833240f027b25eff": "0x_exchange_proxy",
    # Paraswap
    "0xdef171fe48cf0115b1d80b88dc8eab59176fee57": "paraswap_v5",
    "0x6a000f20005980200259b80c5102003040001068": "paraswap_v6_2",
    # CoW Protocol
    "0x9008d19f58aabd9ed0d60971565aa8510560ab41": "cowswap_settlement",
    # KyberSwap
    "0x6131b5fae19ea4f9d964eac0408e4408b66337b5": "kyberswap_meta_v2",
}

ROUTER_SET = frozenset(ROUTERS)
