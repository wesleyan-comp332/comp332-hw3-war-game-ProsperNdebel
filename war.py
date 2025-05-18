"""
war card game client and server
"""
import asyncio
from collections import namedtuple
from enum import Enum
import logging
import random
import socket
import socketserver
import threading
import sys
"""
Namedtuples work like classes, but are much more lightweight so they end
up being faster. It would be a good idea to keep objects in each of these
for each game which contain the game's state, for instance things like the
socket, the cards given, the cards still available, etc.
"""
Game = namedtuple("Game", ["p1", "p2"])
# Stores the clients waiting to get connected to other clients
waiting_clients = []

class Command(Enum):
    """
    The byte values sent as the first byte of any message in the war protocol.
    """
    WANTGAME = 0
    GAMESTART = 1
    PLAYCARD = 2
    PLAYRESULT = 3

class Result(Enum):
    """
    The byte values sent as the payload byte of a PLAYRESULT message.
    """
    WIN = 0
    DRAW = 1
    LOSE = 2

def readexactly(sock, numbytes):
    """
    Accumulate exactly `numbytes` from `sock` and return those. If EOF is found
    before numbytes have been received, be sure to account for that here or in
    the caller.
    """
    data = bytearray()
    while len(data) < numbytes:
        packet = sock.recv(numbytes - len(data))
        if not packet:  # EOF
            return data
        data.extend(packet)
    return data

def kill_game(game):
    """
    If either client sends a bad message, immediately nuke the game.
    """
    logging.info("Killing game between clients")
    try:
        game.p1.close()
    except:
        pass
    try:
        game.p2.close()
    except:
        pass

def compare_cards(card1, card2):
    """
    Given an integer card representation, return -1 for card1 < card2,
    0 for card1 = card2, and 1 for card1 > card2
    """
    rank1 = card1 % 13
    rank2 = card2 % 13
    
    if rank1 < rank2:
        return -1
    elif rank1 > rank2:
        return 1
    else:
        return 0
    
def deal_cards():
    """
    Randomize a deck of cards (list of ints 0..51), and return two
    26 card "hands."
    """
    deck = list(range(52))
    random.shuffle(deck)
    return deck[:26], deck[26:]

def handle_client_connection(game):
    """
    Handle a game between two clients.
    """
    p1_socket, p2_socket = game.p1, game.p2
    
    try:
        p1_cards, p2_cards = deal_cards()
        
        p1_socket.sendall(bytes([Command.GAMESTART.value]) + bytes(p1_cards))
        p2_socket.sendall(bytes([Command.GAMESTART.value]) + bytes(p2_cards))
        
        p1_played_cards = set()
        p2_played_cards = set()
        
        for _ in range(26):
            p1_msg = readexactly(p1_socket, 2)
            if len(p1_msg) < 2 or p1_msg[0] != Command.PLAYCARD.value:
                logging.error("Invalid message from Player 1")
                kill_game(game)
                return
            
            p1_card = p1_msg[1]
            
            if p1_card not in p1_cards or p1_card in p1_played_cards:
                logging.error("Player 1 played invalid card")
                kill_game(game)
                return
            
            p1_played_cards.add(p1_card)
            
            p2_msg = readexactly(p2_socket, 2)
            if len(p2_msg) < 2 or p2_msg[0] != Command.PLAYCARD.value:
                logging.error("Invalid message from Player 2")
                kill_game(game)
                return
            
            p2_card = p2_msg[1]
            
            if p2_card not in p2_cards or p2_card in p2_played_cards:
                logging.error("Player 2 played invalid card")
                kill_game(game)
                return
            
            p2_played_cards.add(p2_card)
            
            result = compare_cards(p1_card, p2_card)
            
            if result > 0:  
                p1_socket.sendall(bytes([Command.PLAYRESULT.value, Result.WIN.value]))
                p2_socket.sendall(bytes([Command.PLAYRESULT.value, Result.LOSE.value]))
            elif result < 0: 
                p1_socket.sendall(bytes([Command.PLAYRESULT.value, Result.LOSE.value]))
                p2_socket.sendall(bytes([Command.PLAYRESULT.value, Result.WIN.value]))
            else:  
                p1_socket.sendall(bytes([Command.PLAYRESULT.value, Result.DRAW.value]))
                p2_socket.sendall(bytes([Command.PLAYRESULT.value, Result.DRAW.value]))
        
        p1_socket.close()
        p2_socket.close()
        
    except Exception as e:
        logging.error(f"Error in game: {e}")
        kill_game(game)

def serve_game(host, port):
    """
    Open a socket for listening for new connections on host:port, and
    perform the war protocol to serve a game of war between each client.
    This function should run forever, continually serving clients.
    """
    server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    
    server_socket.bind((host, port))
    
    server_socket.listen(128) 
    
    logging.info(f"War server started on {host}:{port}")
    
    games = []
    
    while True:
        client_socket, client_address = server_socket.accept()
        logging.info(f"New connection from {client_address}")
        
        try:
            msg = readexactly(client_socket, 2)
            
            if len(msg) < 2 or msg[0] != Command.WANTGAME.value:
                logging.error(f"Client {client_address} sent invalid initial message")
                client_socket.close()
                continue
            
            if not waiting_clients:
                waiting_clients.append(client_socket)
                logging.info(f"Client {client_address} waiting for opponent")
            else:
                opponent_socket = waiting_clients.pop(0)
                
                game = Game(opponent_socket, client_socket)
                
                game_thread = threading.Thread(target=handle_client_connection, args=(game,))
                game_thread.daemon = True
                game_thread.start()
                
                games.append(game)
                logging.info("Game started")
                
        except Exception as e:
            logging.error(f"Error handling client: {e}")
            client_socket.close()
    
async def limit_client(host, port, loop, sem):
    """
    Limit the number of clients currently executing.
    You do not need to change this function.
    """
    async with sem:
        return await client(host, port, loop)

async def client(host, port, loop):
    """
    Run an individual client on a given event loop.
    You do not need to change this function.
    """
    try:
        reader, writer = await asyncio.open_connection(host, port)
        # send want game
        writer.write(b"\0\0")
        card_msg = await reader.readexactly(27)
        myscore = 0
        for card in card_msg[1:]:
            writer.write(bytes([Command.PLAYCARD.value, card]))
            result = await reader.readexactly(2)
            if result[1] == Result.WIN.value:
                myscore += 1
            elif result[1] == Result.LOSE.value:
                myscore -= 1
        if myscore > 0:
            result = "won"
        elif myscore < 0:
            result = "lost"
        else:
            result = "drew"
        logging.debug("Game complete, I %s", result)
        writer.close()
        return 1
    except ConnectionResetError:
        logging.error("ConnectionResetError")
        return 0
    except asyncio.IncompleteReadError:  
        logging.error("IncompleteReadError")
        return 0
    except OSError:
        logging.error("OSError")
        return 0

def main(args):
    """
    launch a client/server
    """
    host = args[1]
    port = int(args[2])
    if args[0] == "server":
        try:
            # your server should serve clients until the user presses ctrl+c
            serve_game(host, port)
        except KeyboardInterrupt:
            pass
        return
    else:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
        
        asyncio.set_event_loop(loop)
        
    if args[0] == "client":
        loop.run_until_complete(client(host, port, loop))
    elif args[0] == "clients":
        sem = asyncio.Semaphore(1000)
        num_clients = int(args[3])
        clients = [limit_client(host, port, loop, sem)
                   for x in range(num_clients)]
        async def run_all_clients():
            """
            use `as_completed` to spawn all clients simultaneously
            and collect their results in arbitrary order.
            """
            completed_clients = 0
            for client_result in asyncio.as_completed(clients):
                completed_clients += await client_result
            return completed_clients
        res = loop.run_until_complete(
            run_all_clients())
        logging.info("%d completed clients", res)
    loop.close()

if __name__ == "__main__":
    # Changing logging to DEBUG
    logging.basicConfig(level=logging.DEBUG)
    main(sys.argv[1:])