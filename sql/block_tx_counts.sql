-- Per-block tx counts + next-block timestamp for intra-block position
-- normalization (§17.7). Export to data/onchain/blocks/.
SELECT
    b.number                                        AS block_number,
    b.time                                          AS block_time,
    LEAD(b.time) OVER (ORDER BY b.number)           AS next_block_time,
    (SELECT COUNT(*) FROM ethereum.transactions t
      WHERE t.block_number = b.number)              AS tx_count
FROM ethereum.blocks b
WHERE b.time >= TIMESTAMP '2026-03-01 00:00'
  AND b.time <  TIMESTAMP '2026-09-01 00:00'
ORDER BY b.number
