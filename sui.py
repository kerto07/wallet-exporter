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


def get_coin_metadata(rpc_url, coin_type, rpc_call_status_counter):
    """
    Get coin metadata including decimals from Sui RPC

    Args:
        rpc_url: The Sui RPC endpoint URL
        coin_type: The coin type string (e.g., "0x2::sui::SUI")
        rpc_call_status_counter: Prometheus counter for RPC call status

    Returns:
        dict: Metadata with 'decimals', 'symbol', 'name' keys
    """
    try:
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "suix_getCoinMetadata",
            "params": [coin_type],
        }

        response = http_json_call(
            url=rpc_url,
            rpc_call_status_counter=rpc_call_status_counter,
            params=payload,
            method="POST",
        )

        if "result" in response and response["result"]:
            result = response["result"]
            return {
                "decimals": result.get("decimals", 0),
                "symbol": result.get("symbol", "UNKNOWN"),
                "name": result.get("name", ""),
            }
        else:
            # Default fallback
            return {"decimals": 0, "symbol": "UNKNOWN", "name": ""}

    except Exception:
        # If metadata fetch fails, return defaults
        return {"decimals": 0, "symbol": "UNKNOWN", "name": ""}


def get_sui_coin_balance_by_symbols(
    rpc_url, address, symbols=None, rpc_call_status_counter=None
):
    """
    Get balance for specific coins by symbols.
    Always includes SUI balance, plus any additional symbols requested.

    Args:
        rpc_url: The Sui RPC endpoint URL
        address: The Sui wallet address
        symbols: Optional comma-separated string or list of symbols
                 (e.g., 'IKA' or 'IKA,WAL' or ['IKA', 'WAL']).
                 If None/empty, only returns SUI balance.
        rpc_call_status_counter: Prometheus counter for RPC call status

    Returns:
        list: List of dicts with 'balance' and 'symbol' keys
    """
    try:
        # Parse symbols parameter
        target_symbols = []
        if symbols:
            if isinstance(symbols, str):
                target_symbols = [s.strip().upper() for s in symbols.split(",")]
            elif isinstance(symbols, list):
                target_symbols = [s.strip().upper() for s in symbols]

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
        sui_found = False
        found_symbols = set()

        # Process all coin types
        for coin_balance in response["result"]:
            coin_type = coin_balance.get("coinType", "")
            total_balance = int(coin_balance.get("totalBalance", 0))

            # Always include SUI (gas token)
            if coin_type == "0x2::sui::SUI":
                # Fetch metadata to get decimals for SUI
                metadata = get_coin_metadata(
                    rpc_url, coin_type, rpc_call_status_counter
                )
                decimals = metadata.get("decimals", 9)  # Default to 9 for SUI

                balance_sui = total_balance / (10**decimals)
                balances.append({"balance": balance_sui, "symbol": "SUI"})
                sui_found = True
            else:
                # Extract symbol from coin type
                coin_symbol = (
                    coin_type.split("::")[-1] if "::" in coin_type else "UNKNOWN"
                )

                # Check if this matches any requested symbol
                if target_symbols and coin_symbol.upper() in target_symbols:
                    # Fetch metadata to get decimals
                    metadata = get_coin_metadata(
                        rpc_url, coin_type, rpc_call_status_counter
                    )
                    decimals = metadata.get("decimals", 0)

                    # Apply decimals if available
                    if decimals > 0:
                        balance = total_balance / (10**decimals)
                    else:
                        balance = total_balance

                    balances.append({"balance": balance, "symbol": coin_symbol})
                    found_symbols.add(coin_symbol.upper())

        # If SUI wasn't found, add it with 0 balance
        if not sui_found:
            balances.insert(0, {"balance": 0.0, "symbol": "SUI"})

        # If target symbols were specified but not found, add with 0
        for target_symbol in target_symbols:
            if target_symbol not in found_symbols:
                balances.append({"balance": 0.0, "symbol": target_symbol})

        rpc_call_status_counter.labels(
            url=rpc_url, status=MetricsUrlStatus.SUCCESS.value
        ).inc()

        return balances

    except Exception as err:
        rpc_call_status_counter.labels(
            url=rpc_url, status=MetricsUrlStatus.FAILED.value
        ).inc()
        raise err
