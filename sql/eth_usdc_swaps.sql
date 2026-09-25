-- ETH/USDC 0.05% Uniswap v3 mainnet swaps with tx context (§17.3).
-- Pool: 0x88e6a0c2ddd26feeb64f039a2c41296fcb3f5640 (token0 = USDC 6dp, token1 = WETH 18dp)
-- amount0/amount1 are POOL-PERSPECTIVE signed deltas: > 0 pool received, < 0 pool sent.
-- Committed for reproducibility (§17.9). Run on Dune, export as Parquet/CSV
-- to data/onchain/eth_usdc_swaps/.
SELECT
    s.evt_block_number                 AS block_number,
    s.evt_block_time                   AS block_time,
    s.evt_tx_hash                      AS tx_hash,
    s.evt_index                        AS log_index,
    t."index"                          AS tx_index,
    t."from"                           AS tx_from,
    t.to                               AS tx_to,
    t.priority_fee_per_gas             AS priority_fee_per_gas,
    t.gas_used                         AS gas_used,
    s.sender                           AS swap_sender,
    s.recipient                        AS swap_recipient,
    s.amount0                          AS amount0_usdc_raw,
    s.amount1                          AS amount1_weth_raw,
    s.sqrtPriceX96,
    s.liquidity,
    s.tick
FROM uniswap_v3_ethereum.UniswapV3Pool_evt_Swap s
JOIN ethereum.transactions t
    ON t.hash = s.evt_tx_hash
   AND t.block_number = s.evt_block_number
WHERE s.contract_address = 0x88e6a0c2ddd26feeb64f039a2c41296fcb3f5640
  AND s.evt_block_time >= TIMESTAMP '2026-03-01 00:00'
  AND s.evt_block_time <  TIMESTAMP '2026-09-01 00:00'
ORDER BY s.evt_block_number, s.evt_index
