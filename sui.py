"""Sui blockchain wallet functions"""

from metrics_enum import MetricsUrlStatus
from utils import http_json_call


def get_sui_balance_simple(rpc_url, address, rpc_call_status_counter):
    """
    Get only SUI native token balance (simplified version)

    Args:
        rpc_url: The Sui RPC endpoint URL
        address: The Sui wallet address
        rpc_call_status_counter: Prometheus counter for RPC call status

    Returns:
        float: SUI balance
    """
    try:
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "suix_getBalance",
            "params": [address, "0x2::sui::SUI"],
        }

        response = http_json_call(
            url=rpc_url,
            rpc_call_status_counter=rpc_call_status_counter,
            params=payload,
            method="POST",
        )

        if "result" not in response:
            raise Exception(f"Invalid response from Sui RPC: {response}")

        total_balance = int(response["result"].get("totalBalance", 0))
        balance_sui = total_balance / 10**9  # SUI has 9 decimals

        rpc_call_status_counter.labels(
            url=rpc_url, status=MetricsUrlStatus.SUCCESS.value
        ).inc()

        return balance_sui

    except Exception as err:
        rpc_call_status_counter.labels(
            url=rpc_url, status=MetricsUrlStatus.FAILED.value
        ).inc()
        raise err


def get_sui_coin_balance_by_symbol(
    rpc_url, address, symbol=None, rpc_call_status_counter=None
):
    """
    Get balance for specific coin by symbol.
    If symbol is None: returns only SUI balance.
    If symbol is specified: returns only that symbol's balance.

    Args:
        rpc_url: The Sui RPC endpoint URL
        address: The Sui wallet address
        symbol: Optional coin symbol to fetch (e.g., 'IKA', 'USDC').
                If None, only returns SUI balance.
                If specified, only returns that symbol's balance.
        rpc_call_status_counter: Prometheus counter for RPC call status

    Returns:
        list: List of dicts with 'balance' and 'symbol' keys
    """
    try:
        # Get all coin balances for the address
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "suix_getAllBalances",
            "params": [address],
        }

        response = http_json_call(
            url=rpc_url,
            rpc_call_status_counter=rpc_call_status_counter,
            params=payload,
            method="POST",
        )

        if "result" not in response:
            raise Exception(f"Invalid response from Sui RPC: {response}")

        balances = []

        # If no specific symbol requested, return only SUI
        if symbol is None:
            for coin_balance in response["result"]:
                coin_type = coin_balance.get("coinType", "")
                if coin_type == "0x2::sui::SUI":
                    total_balance = int(coin_balance.get("totalBalance", 0))
                    balance_sui = total_balance / 10**9
                    balances.append({"balance": balance_sui, "symbol": "SUI"})
                    break
            # If SUI not found, return 0
            if not balances:
                balances.append({"balance": 0.0, "symbol": "SUI"})
        else:
            # Looking for specific symbol
            target_found = False
            for coin_balance in response["result"]:
                coin_type = coin_balance.get("coinType", "")
                total_balance = int(coin_balance.get("totalBalance", 0))

                # Extract symbol from coin type
                coin_symbol = (
                    coin_type.split("::")[-1] if "::" in coin_type else "UNKNOWN"
                )

                # Check if this matches the requested symbol
                if coin_symbol.upper() == symbol.upper():
                    # For now, return raw balance
                    # In production, you'd want to fetch decimals
                    balances.append({"balance": total_balance, "symbol": coin_symbol})
                    target_found = True
                    break

            # If target symbol not found, return 0
            if not target_found:
                balances.append({"balance": 0.0, "symbol": symbol})

        rpc_call_status_counter.labels(
            url=rpc_url, status=MetricsUrlStatus.SUCCESS.value
        ).inc()

        return balances

    except Exception as err:
        rpc_call_status_counter.labels(
            url=rpc_url, status=MetricsUrlStatus.FAILED.value
        ).inc()
        raise err
