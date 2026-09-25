import { UniswapV3Pool } from "generated";

UniswapV3Pool.Swap.handler(async ({ event, context }) => {
  context.Swap.set({
    id: `${event.chainId}_${event.block.number}_${event.logIndex}`,
    pool: event.srcAddress.toLowerCase(),
    blockNumber: event.block.number,
    blockTimestamp: event.block.timestamp,
    txIndex: event.transaction.transactionIndex,
    logIndex: event.logIndex,
    txHash: event.transaction.hash,
    txFrom: event.transaction.from?.toLowerCase(),
    txTo: event.transaction.to?.toLowerCase(),
    gasPrice: event.transaction.gasPrice,
    maxFeePerGas: event.transaction.maxFeePerGas,
    maxPriorityFeePerGas: event.transaction.maxPriorityFeePerGas,
    sender: event.params.sender.toLowerCase(),
    recipient: event.params.recipient.toLowerCase(),
    amount0: event.params.amount0,
    amount1: event.params.amount1,
    sqrtPriceX96: event.params.sqrtPriceX96,
    liquidity: event.params.liquidity,
    tick: event.params.tick,
  });
});
