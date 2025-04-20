import time
from web3 import Web3
from web3.exceptions import ContractLogicError
import logging

# 配置常规日志（记录到 betting.log 和控制台，使用中文）
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    filename='betting.log'
)
logger = logging.getLogger(__name__)
console_handler = logging.StreamHandler()
console_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
logger.addHandler(console_handler)

# 配置胜利日志（记录到 ok.log 和控制台，使用中文）
ok_logger = logging.getLogger('ok_logger')
ok_handler = logging.FileHandler('ok.log')
ok_handler.setFormatter(logging.Formatter('%(asctime)s - 竞猜ID: %(betId)s, 奖励哈希: %(rewardTxId)s'))
ok_logger.addHandler(ok_handler)
ok_console_handler = logging.StreamHandler()
ok_console_handler.setFormatter(logging.Formatter('%(asctime)s - 竞猜ID: %(betId)s, 奖励哈希: %(rewardTxId)s'))
ok_logger.addHandler(ok_console_handler)
ok_logger.setLevel(logging.INFO)

# 合约 ABI（更新为新合约，去掉 level 参数）
CONTRACT_ABI = [
    {
        "inputs": [
            {"internalType": "string", "name": "guess", "type": "string"},
            {"internalType": "uint256", "name": "amount", "type": "uint256"}
        ],
        "name": "placeBet",
        "outputs": [{"internalType": "uint256", "name": "", "type": "uint256"}],
        "stateMutability": "nonpayable",
        "type": "function"
    },
    {
        "inputs": [{"internalType": "uint256", "name": "betId", "type": "uint256"}],
        "name": "resolveBet",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function"
    },
    {
        "inputs": [{"internalType": "uint256", "name": "betId", "type": "uint256"}],
        "name": "getBet",
        "outputs": [
            {
                "components": [
                    {"internalType": "address", "name": "user", "type": "address"},
                    {"internalType": "string", "name": "guess", "type": "string"},
                    {"internalType": "uint256", "name": "amount", "type": "uint256"},
                    {"internalType": "bytes1", "name": "targetByte", "type": "bytes1"},
                    {"internalType": "bool", "name": "won", "type": "bool"},
                    {"internalType": "uint256", "name": "reward", "type": "uint256"},
                    {"internalType": "uint256", "name": "blockNumber", "type": "uint256"},
                    {"internalType": "bool", "name": "resolved", "type": "bool"}
                ],
                "internalType": "struct GuessCounterGame.Bet",
                "name": "",
                "type": "tuple"
            }
        ],
        "stateMutability": "view",
        "type": "function"
    },
    {
        "inputs": [],
        "name": "betCounter",
        "outputs": [{"internalType": "uint256", "name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function"
    },
    {
        "anonymous": False,
        "inputs": [
            {"indexed": True, "internalType": "uint256", "name": "betId", "type": "uint256"},
            {"indexed": True, "internalType": "address", "name": "user", "type": "address"},
            {"indexed": False, "internalType": "string", "name": "guess", "type": "string"},
            {"indexed": False, "internalType": "uint256", "name": "amount", "type": "uint256"},
            {"indexed": False, "internalType": "uint256", "name": "blockNumber", "type": "uint256"}
        ],
        "name": "BetPlaced",
        "type": "event"
    }
]

# ERC20 ABI（保持不变）
ERC20_ABI = [
    {
        "constant": False,
        "inputs": [
            {"name": "_spender", "type": "address"},
            {"name": "_value", "type": "uint256"}
        ],
        "name": "approve",
        "outputs": [{"name": "", "type": "bool"}],
        "type": "function"
    },
    {
        "constant": True,
        "inputs": [
            {"name": "_owner", "type": "address"},
            {"name": "_spender", "type": "address"}
        ],
        "name": "allowance",
        "outputs": [{"name": "", "type": "uint256"}],
        "type": "function"
    }
]

# 配置参数（替换为实际值）
RPC_URL = "https://sepolia.base.org"
CONTRACT_ADDRESS = "0x34308cA4FDa08A95b7F7B643124588DD4Fa5158c"
TOKEN_ADDRESS = "0xE8edF2DF7847A53Aeb6738FDE69BCa923Ca5C195"
PRIVATE_KEY = "123456"  # 请替换为实际私钥
ACCOUNT_ADDRESS = "123456"  # 请替换为实际账户地址
COOLDOWN = 2  # 冷却时间（秒）
BLOCK_WAIT_TIME = 4  # 等待 2 个块（约 4 秒）

def initialize_web3():
    try:
        w3 = Web3(Web3.HTTPProvider(RPC_URL))
        if not w3.is_connected():
            logger.error("无法连接到 RPC 节点")
            raise Exception("无法连接到 RPC 节点")
        return w3
    except Exception as e:
        logger.error(f"Web3 初始化失败: {str(e)}")
        raise

def approve_token(w3, token_contract, amount, num_bets):
    try:
        account_address = w3.to_checksum_address(ACCOUNT_ADDRESS)
        contract_address = w3.to_checksum_address(CONTRACT_ADDRESS)
        
        allowance = token_contract.functions.allowance(account_address, contract_address).call()
        required_amount = amount * num_bets
        if allowance < required_amount:
            tx = token_contract.functions.approve(
                contract_address,
                required_amount
            ).build_transaction({
                'from': account_address,
                'nonce': w3.eth.get_transaction_count(account_address),
                'gas': 100000,
                'gasPrice': w3.eth.gas_price
            })
            signed_tx = w3.eth.account.sign_transaction(tx, PRIVATE_KEY)
            tx_hash = w3.eth.send_raw_transaction(signed_tx.raw_transaction)
            receipt = w3.eth.wait_for_transaction_receipt(tx_hash)
            logger.info(f"授权代币 {required_amount} 单位, 交易哈希: {tx_hash.hex()}, 区块号: {receipt.blockNumber}")
    except Exception as e:
        logger.error(f"代币授权失败: {str(e)}")
        raise

def place_bet(w3, contract, guess, amount):
    try:
        account_address = w3.to_checksum_address(ACCOUNT_ADDRESS)
        tx = contract.functions.placeBet(
            guess,
            amount
        ).build_transaction({
            'from': account_address,
            'nonce': w3.eth.get_transaction_count(account_address),
            'gas': 400000,
            'gasPrice': w3.eth.gas_price
        })
        signed_tx = w3.eth.account.sign_transaction(tx, PRIVATE_KEY)
        tx_hash = w3.eth.send_raw_transaction(signed_tx.raw_transaction)
        receipt = w3.eth.wait_for_transaction_receipt(tx_hash)
        logger.info(f"竞猜成功: 交易哈希=0x{tx_hash.hex()}, 竞猜所在区块号={receipt.blockNumber}")
        return receipt, tx_hash.hex()
    except ContractLogicError as e:
        logger.error(f"合约错误: {str(e)}")
        raise
    except Exception as e:
        logger.error(f"竞猜失败: {str(e)}")
        raise

def resolve_bet(w3, contract, bet_id):
    try:
        account_address = w3.to_checksum_address(ACCOUNT_ADDRESS)
        tx = contract.functions.resolveBet(
            bet_id
        ).build_transaction({
            'from': account_address,
            'nonce': w3.eth.get_transaction_count(account_address),
            'gas': 200000,
            'gasPrice': w3.eth.gas_price
        })
        signed_tx = w3.eth.account.sign_transaction(tx, PRIVATE_KEY)
        tx_hash = w3.eth.send_raw_transaction(signed_tx.raw_transaction)
        receipt = w3.eth.wait_for_transaction_receipt(tx_hash)

        bet = contract.functions.getBet(bet_id).call()
        block_number = bet[6]  # Updated index due to removed 'level' field
        block_hash = w3.eth.get_block(block_number)['hash'].hex()
        logger.info(f"竞猜ID {bet_id} 区块哈希: 0x{block_hash}, 区块号: {block_number}")
        target_byte = chr(int.from_bytes(bet[3], byteorder='big'))  # Updated index
        logger.info(f"竞猜ID {bet_id} 区块尾值为: {target_byte}")

        return bet, tx_hash.hex()
    except ContractLogicError as e:
        logger.error(f"解析竞猜 {bet_id} 失败: {str(e)}")
        raise
    except Exception as e:
        logger.error(f"解析竞猜 {bet_id} 失败: {str(e)}")
        raise

def get_user_input(w3):
    while True:
        guess = input("请输入竞猜字符（0-9 或 a-f）：").strip().lower()
        if guess in "0123456789abcdef":
            break
        print("无效输入，字符必须是 0-9 或 a-f")

    while True:
        try:
            bet_amount = float(input("请输入每次竞猜数量（币，如 100）：").strip())
            if bet_amount <= 0:
                print("竞猜数量必须为正数")
                continue
            break
        except ValueError:
            print("无效输入，请输入一个正数")

    while True:
        try:
            num_bets = int(input("请输入竞猜次数（正整数，如 100）：").strip())
            if num_bets <= 0:
                print("竞猜次数必须为正整数")
                continue
            break
        except ValueError:
            print("无效输入，请输入一个正整数")

    # 转换为 Wei
    bet_amount_wei = w3.to_wei(bet_amount, 'ether')

    return guess, num_bets, bet_amount_wei

def auto_bet():
    w3 = initialize_web3()
    contract_address = w3.to_checksum_address(CONTRACT_ADDRESS)
    token_address = w3.to_checksum_address(TOKEN_ADDRESS)
    
    contract = w3.eth.contract(address=contract_address, abi=CONTRACT_ABI)
    token_contract = w3.eth.contract(address=token_address, abi=ERC20_ABI)

    # 获取用户输入
    guess, num_bets, bet_amount = get_user_input(w3)
    print(f"条件为：竞猜={guess}, 每次={w3.from_wei(bet_amount, 'ether')}币, 次数={num_bets}")

    approve_token(w3, token_contract, bet_amount, num_bets)

    successful_bets = 0
    for i in range(num_bets):
        try:
            logger.info(f"尝试竞猜次序 {i+1}/{num_bets}: 你的竞猜内容为={guess}")
            receipt, tx_hash = place_bet(w3, contract, guess, bet_amount)
            successful_bets += 1

            bet_id = None
            for log in receipt['logs']:
                if log['address'].lower() == contract_address.lower():
                    try:
                        bet_id = w3.eth.contract(abi=CONTRACT_ABI).events.BetPlaced().process_log(log)['args']['betId']
                        break
                    except:
                        continue

            if bet_id is None:
                logger.error(f"无法提取竞猜ID，交易哈希: {tx_hash}")
                continue

            time.sleep(BLOCK_WAIT_TIME)

            bet, resolve_tx_hash = resolve_bet(w3, contract, bet_id)
            won = bet[4]  # Updated index
            reward = bet[5]  # Updated index
            reward_in_tokens = float(w3.from_wei(reward, 'ether'))

            if won:
                ok_logger.info(
                    "",
                    extra={
                        'betId': bet_id,
                        'rewardTxId': resolve_tx_hash
                    }
                )
                logger.info(f"发送奖励哈希: 0x{resolve_tx_hash}, {reward_in_tokens} 代币")
                logger.info(f"////////////////////////////////////////////////////////////////////")
                logger.info(f"//                                                                //")
                logger.info(f"//    恭喜！竞猜ID {bet_id} 获胜！奖励{reward_in_tokens} 代币已自动发送到你的地址    //")
                logger.info(f"//                                                                //")
                logger.info(f"////////////////////////////////////////////////////////////////////")

            time.sleep(COOLDOWN + 1)

        except Exception as e:
            logger.error(f"第 {i+1} 次竞猜失败: {str(e)}")
            continue

    logger.info(f"完成：{successful_bets}/{num_bets} 次竞猜成功")

def main():
    print("-------------------------------------------------------------")
    print("针对竞猜所在区块哈希尾号内容的字符值，猜0-9 或 a-f")
    print("竞猜正确赢得投注额 *12 倍奖励，竞猜错误失去投注额币")
    print("交易哈希值不是区块哈希值，区块哈希可包含多个交易哈希")
    print("为保证公平公开透明，仅针对竞猜时产生的区块哈希尾号值")
    print("为什么要用区块哈希值，因为无法预知竞猜时的区块哈希值")
    print("为什么不用交易哈希值，修改gas、nonce可能影响哈希值")
    print("-------------------------------------------------------------")
    auto_bet()

if __name__ == "__main__":
    main()
