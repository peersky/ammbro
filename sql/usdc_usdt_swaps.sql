-- USDC/USDT 0.01% Uniswap v3 mainnet swaps — calm-period control pool (§17.3.2).
-- Pool: 0x3416cf6c708da44db2624d63ea0aaef7113527c6 (token0 = USDC 6dp, token1 = USDT 6dp)
-- Control role only: q_LP magnitudes here must match the observable peg band.
-- Never used for fee sweep or REP ablation.
SELECT
    s.evt_block_number                 AS block_number,
    s.evt_block_time                   AS block_time,
    s.evt_tx_hash                      AS tx_hash,
    s.evt_index                        AS log_index,
    t."index"                          AS tx_index,
    t."from"                           AS tx_from,
    t.to                               AS tx_to,
    s.amount0                          AS amount0_usdc_raw,
    s.amount1                          AS amount1_usdt_raw,
    s.sqrtPriceX96,
    s.tick
FROM uniswap_v3_ethereum.UniswapV3Pool_evt_Swap s
JOIN ethereum.transactions t
    ON t.hash = s.evt_tx_hash
   AND t.block_number = s.evt_block_number
WHERE s.contract_address = 0x3416cf6c708da44db2624d63ea0aaef7113527c6
  AND s.evt_block_time >= TIMESTAMP '2026-03-01 00:00'
  AND s.evt_block_time <  TIMESTAMP '2026-09-01 00:00'
ORDER BY s.evt_block_number, s.evt_index
