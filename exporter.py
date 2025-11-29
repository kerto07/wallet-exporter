"""Application exporter"""

import argparse
import os
import time

from bera import (
    get_bera_boostees,
    get_bera_boosts,
    get_bera_queued_boost,
    get_bera_unboosted,
)
from cosmos import (
    get_cosmos_registry,
    get_delegations,
    get_maincoin_balance,
    get_rewards,
    get_unbonding_delegations,
)
from dotenv import load_dotenv
from ethereum import get_ethereum_balance, get_evm_chains_data
from metrics_enum import MetricsAccountInfo, NetworkType, TokenType
from prometheus_client import Counter, Gauge, start_http_server
from solana_wallet import get_solana_balance
from substrate import get_substrate_account_balance
from sui import get_sui_coin_balance_by_symbols
from utils import configure_logging, read_config_file


class AppMetrics:
    """
    Representation of Prometheus metrics and loop to fetch and transform
    application metrics into Prometheus metrics.
    """

    def __init__(self, polling_interval_seconds=60, walletconfig=False, logging=False):
        self.polling_interval_seconds = polling_interval_seconds

        self.logging = logging
        self.logging.info("Init the Appmetrics class")
        self.walletconfig = walletconfig

        # all metrics are defined below
        self.account_info = Gauge(
            "account_info",
            "account information",
            ["address", "name", "network", "type", "token", "token_type"],
        )
        self.rpc_call_status_counter = Counter(
            "rpc_call_status",
            "Count the number of success or failed http call for a given url",
            ["url", "status"],
        )
        self.cosmos_registry = get_cosmos_registry(
            "mainnet", self.rpc_call_status_counter
        )
        self.cosmos_testnet_registry = get_cosmos_registry(
            "testnet", self.rpc_call_status_counter
        )
        self.chains_evm = get_evm_chains_data(self.rpc_call_status_counter)

        logging.debug(walletconfig)

    def run_metrics_loop(self):
        """Metrics fetching loop"""

        while True:
            self.fetch()
            time.sleep(self.polling_interval_seconds)

    def _set_balance_metric(self, network_name, wallet, balance, symbol, token_type):
        """Helper method to set balance metrics and log information."""
        self.logging.info(f"{wallet['address']} has {balance} {symbol}")
        self.account_info.labels(
            network=network_name,
            address=wallet["address"],
            name=wallet["name"],
            token=symbol,
            token_type=token_type,
            type=MetricsAccountInfo.BALANCE.value,
        ).set(balance)

    def fetch_balance(self, network, wallet, chain_registry):
        network_name = network["name"]
        network_type = network["type"]
        balance = 0

        if network_type == NetworkType.COSMOS.value:
            balance = float(
                get_maincoin_balance(
                    network["api"],
                    wallet["address"],
                    chain_registry["denom"],
                    self.rpc_call_status_counter,
                )
            ) / (10 ** chain_registry["decimals"])
            self._set_balance_metric(
                network_name,
                wallet,
                balance,
                chain_registry["symbol"],
                TokenType.NATIVE.value,
            )
        elif (
            network_type == NetworkType.EVM.value
            or network_type == NetworkType.BERA.value
        ):
            balances_data = get_ethereum_balance(
                apiprovider=network["api"],
                wallet=wallet,
                rpc_call_status_counter=self.rpc_call_status_counter,
                chains_evm=self.chains_evm,
            )
            for balance_data in balances_data:
                balance = balance_data["balance"]
                symbol = balance_data["symbol"]
                self.logging.info(f"{wallet['address']} has {balance} {symbol}")
                self.account_info.labels(
                    network=network_name,
                    address=wallet["address"],
                    name=wallet["name"],
                    token_type=balance_data["token_type"],
                    token=symbol,
                    type=MetricsAccountInfo.BALANCE.value,
                ).set(balance)
        elif network_type == NetworkType.SUBSTRATE.value:
            substrate_info = get_substrate_account_balance(
                node_url=network["api"],
                address=wallet["address"],
                rpc_call_status_counter=self.rpc_call_status_counter,
            )
            balance = substrate_info.get("balance") / 10 ** substrate_info.get(
                "decimals"
            )
            symbol = substrate_info.get("symbol")
            self._set_balance_metric(
                network_name, wallet, balance, symbol, TokenType.NATIVE.value
            )
        elif network_type == NetworkType.SOLANA.value:
            solana_info = get_solana_balance(
                rpc_url=network["rpc"],
                address=wallet["address"],
                rpc_call_status_counter=self.rpc_call_status_counter,
            )
            balance = solana_info.get("balance")
            symbol = solana_info.get("symbol")
            self._set_balance_metric(
                network_name, wallet, balance, symbol, TokenType.NATIVE.value
            )
        elif network_type == NetworkType.SUI.value:
            # Get wallet symbols if specified, otherwise None (SUI only)
            target_symbols = wallet.get("symbols", None)
            balances_data = get_sui_coin_balance_by_symbols(
                rpc_url=network["rpc"],
                address=wallet["address"],
                symbols=target_symbols,
                rpc_call_status_counter=self.rpc_call_status_counter,
            )
            for balance_data in balances_data:
                balance = balance_data["balance"]
                symbol = balance_data["symbol"]
                self._set_balance_metric(
                    network_name, wallet, balance, symbol, TokenType.NATIVE.value
                )

    def fetch_delegations(self, network, wallet, chain_registry):
        network_name = network["name"]
        network_type = network["type"]

        if network_type == NetworkType.COSMOS.value:
            delegations = float(
                get_delegations(
                    network["api"],
                    wallet["address"],
                    chain_registry["denom"],
                    self.rpc_call_status_counter,
                )
            ) / (10 ** chain_registry["decimals"])
            self.logging.info(f"{wallet['address']} has {delegations} delegations")
            self.account_info.labels(
                network=network_name,
                address=wallet["address"],
                name=wallet["name"],
                token=chain_registry["symbol"],
                token_type=TokenType.NATIVE.value,
                type=MetricsAccountInfo.DELEGATIONS.value,
            ).set(delegations)

    def fetch_boosts(self, network, wallet):
        network_name = network["name"]
        network_type = network["type"]

        if network_type == NetworkType.BERA.value:
            bera_boosts = (
                get_bera_boosts(
                    bgt_address=network["bgt_address"],
                    wallet=wallet["address"],
                    api=network["api"],
                )
                / 10**18
            )
            self.logging.info(f"{wallet['address']} has {bera_boosts} bgt boosts")
            self.account_info.labels(
                network=network_name,
                address=wallet["address"],
                name=wallet["name"],
                token="BGT",
                token_type=TokenType.ERC_20.value,
                type=MetricsAccountInfo.BOOSTS.value,
            ).set(bera_boosts)

    def fetch_unbounding_delegations(self, network, wallet, chain_registry):
        network_name = network["name"]
        network_type = network["type"]

        if network_type == NetworkType.COSMOS.value:
            unbounding_delegations = float(
                get_unbonding_delegations(
                    network["api"],
                    wallet["address"],
                    self.rpc_call_status_counter,
                )
            ) / (10 ** chain_registry["decimals"])
            self.logging.info(
                f"{wallet['address']} has {unbounding_delegations} unbounding delegations"
            )
            self.account_info.labels(
                network=network_name,
                address=wallet["address"],
                name=wallet["name"],
                token=chain_registry["symbol"],
                token_type=TokenType.NATIVE.value,
                type=MetricsAccountInfo.UNBOUNDING_DELEGATIONS.value,
            ).set(unbounding_delegations)

    def fetch_rewards(self, network, wallet, chain_registry):
        network_name = network["name"]
        network_type = network["type"]

        if network_type == NetworkType.COSMOS.value:
            rewards = float(
                get_rewards(
                    network["api"],
                    wallet["address"],
                    chain_registry["denom"],
                    self.rpc_call_status_counter,
                )
            ) / (10 ** chain_registry["decimals"])
            self.logging.info(f"{wallet['address']} has {rewards} rewards")
            self.account_info.labels(
                network=network_name,
                address=wallet["address"],
                name=wallet["name"],
                token=chain_registry["symbol"],
                token_type=TokenType.NATIVE.value,
                type=MetricsAccountInfo.REWARDS.value,
            ).set(rewards)

    def fetch_boostees(self, network, wallet):
        network_name = network["name"]
        network_type = network["type"]

        if network_type == NetworkType.BERA.value:
            bera_boostees = (
                get_bera_boostees(
                    bgt_address=network["bgt_address"],
                    wallet=wallet["address"],
                    api=network["api"],
                )
                / 10**18
            )
            self.logging.info(
                f"{wallet['address']} has {bera_boostees} bera attributed to the validator for boosts"
            )
            self.account_info.labels(
                network=network_name,
                address=wallet["address"],
                name=wallet["name"],
                token="BGT",
                token_type=TokenType.ERC_20.value,
                type=MetricsAccountInfo.VALIDATOR_BOOSTEES.value,
            ).set(bera_boostees)

    def fetch_unboosted(self, network, wallet):
        network_name = network["name"]
        network_type = network["type"]

        if network_type == NetworkType.BERA.value:
            bera_unboosted = (
                get_bera_unboosted(
                    bgt_address=network["bgt_address"],
                    wallet=wallet["address"],
                    api=network["api"],
                )
                / 10**18
            )
            self.logging.info(
                f"{wallet['address']} has {bera_unboosted} bera unboosted"
            )
            self.account_info.labels(
                network=network_name,
                address=wallet["address"],
                name=wallet["name"],
                token="BGT",
                token_type=TokenType.ERC_20.value,
                type=MetricsAccountInfo.UNBOOSTED.value,
            ).set(bera_unboosted)

    def fetch_queued_boost(self, network, wallet):
        network_name = network["name"]
        network_type = network["type"]

        if network_type == NetworkType.BERA.value:
            bera_queued_boost = (
                get_bera_queued_boost(
                    bgt_address=network["bgt_address"],
                    wallet=wallet["address"],
                    api=network["api"],
                )
                / 10**18
            )
            self.logging.info(
                f"{wallet['address']} has {bera_queued_boost} bera queued boost"
            )
            self.account_info.labels(
                network=network_name,
                address=wallet["address"],
                name=wallet["name"],
                token="BGT",
                token_type=TokenType.ERC_20.value,
                type=MetricsAccountInfo.QUEUED_BOOST.value,
            ).set(bera_queued_boost)

    def fetch(self):
        """
        Get metrics from application and refresh Prometheus metrics with
        new values.
        """

        self.logging.info("Fetching wallet balances")

        for network in self.walletconfig["networks"]:
            self.logging.debug(network)

            chain_registry = None
            if network["type"] == NetworkType.COSMOS.value:
                for chain in self.cosmos_registry:
                    if chain["name"] == network["name"]:
                        chain_registry = chain
                        break
                if chain_registry is None:
                    # check if it exists in testnet
                    for chain in self.cosmos_testnet_registry:
                        if chain["name"] == network["name"]:
                            chain_registry = chain
                            break
                    if chain_registry is None:
                        self.logging.error(
                            f"Cannot find chain {network} in cosmos registry"
                        )
                        continue

            for wallet in network["wallets"]:
                try:
                    self.logging.info(f"Fetching {wallet['address']}")
                    self.fetch_balance(
                        network=network, wallet=wallet, chain_registry=chain_registry
                    )
                    self.fetch_delegations(
                        network=network, wallet=wallet, chain_registry=chain_registry
                    )
                    self.fetch_unbounding_delegations(
                        network=network, wallet=wallet, chain_registry=chain_registry
                    )
                    self.fetch_rewards(
                        network=network, wallet=wallet, chain_registry=chain_registry
                    )
                    self.fetch_boosts(network=network, wallet=wallet)
                    self.fetch_boostees(network=network, wallet=wallet)
                    self.fetch_unboosted(network=network, wallet=wallet)
                    self.fetch_queued_boost(network=network, wallet=wallet)
                except Exception as e:
                    self.logging.error(str(e))


def argsparse():
    parser = argparse.ArgumentParser(description="Wallets Exporter")
    parser.add_argument(
        "-c",
        "--config",
        help="config file in yaml \
                      format, default is config.yaml",
        action="store",
        default="config.yaml",
    )

    parser.add_argument(
        "-lf",
        "--format",
        choices=["json", "txt"],
        help="set the logging format",
        action="store",
        default="txt",
    )

    parser.add_argument(
        "-ll",
        "--level",
        nargs="?",
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        help="set the logging level",
        action="store",
        default="INFO",
    )

    args = parser.parse_args()
    return args


def main():
    """Main entry point"""

    args = argsparse()
    configfile = args.config
    loglevel = args.level
    logformat = args.format

    log = configure_logging(logformat, loglevel)

    log.debug(f"Argsparse {args}")

    messages, walletconfigs = read_config_file(configfile)

    if not walletconfigs:
        log.error(f"config file {configfile} is incorrect, ${messages}")
        exit(1)
    else:
        log.info(messages)

    log.debug(messages)

    log.debug("Loading .env")
    load_dotenv()  # take environment variables from .env
    polling_interval_seconds = int(os.getenv("POLLING_INTERVAL_SECONDS", "60"))
    exporter_port = int(os.getenv("EXPORTER_PORT", "9877"))

    log.info("Wallet Exporter started and now listening on port " + str(exporter_port))

    app_metrics = AppMetrics(
        polling_interval_seconds=polling_interval_seconds,
        walletconfig=walletconfigs,
        logging=log,
    )
    start_http_server(exporter_port)
    app_metrics.run_metrics_loop()


if __name__ == "__main__":
    main()
