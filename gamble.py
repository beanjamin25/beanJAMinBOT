import json
import random

from exceptions import (
    InsufficientPointsError,
    InvalidBetError,
    BetExceedsBalanceError,
    NoDebtError,
)
from logging_config import get_logger

logger = get_logger('gamble')

DEFAULT_POINTS = 100
POINTS = 'points'
DEBTS = 'debts'

class SimpleGamble:

    def __init__(self, channel, connection, db):
        self.channel = channel
        self.connection = connection

        self.bank = GambleBank(db=db)

    def do_command(self, cmd, user, args):
        c = self.connection
        if cmd == "points":
            points, debts = self.bank.get_points(user)
            msg = f"{user}, you have {points} points"
            if debts > 0:
                msg += f", and you have a debt of {debts} points"
            c.privmsg(self.channel, msg)
            return

        elif cmd == "gamble":
            try:
                win = self.gamble(user, args)
            except InsufficientPointsError:
                c.privmsg(self.channel, f"{user}, you don't have any points to gamble. You can borrow more points with !borrow if you want to keep playing!")
                return
            except InvalidBetError:
                c.privmsg(self.channel, "You need to bet an integer number of points!")
                return
            except BetExceedsBalanceError:
                points, debts = self.bank.get_points(user)
                c.privmsg(self.channel, f"{user}, you cant bet more points than you have! You can either bet all in with !gamble all in, or bet up to {points} points")
                return

            points, debts = self.bank.add_points(user, win)
            if win > 0:
                msg = f"You WIN {user}! You now have {points}"
            else:
                msg = f"You LOSE {user} NotLikeThis You now have {points}"

            if debts > 0:
                msg += f" and {debts} points of debt"

            c.privmsg(self.channel, msg)
            return

        elif cmd == "borrow":
            points, debts = self.bank.borrow(user)
            if points > 0:
                msg = f"{user}, you don't need to borrow any points, you still have {points} points to gamble!"
                c.privmsg(self.channel, msg)
                return

            msg = f"{user}, you now have a debt of {debts} points. Good luck! When you are ready, you can pay back the loan with !payback"
            c.privmsg(self.channel, msg)
            return

        elif cmd == "payback":
            try:
                points, debts = self.bank.payback(user)
            except NoDebtError:
                c.privmsg(self.channel, f"{user}, you're already debt free, silly! You don't need to pay anything back yet!")
                return
            except InsufficientPointsError:
                c.privmsg(self.channel, f"{user}, you don't have any points to pay back your debts with! You'll need to borrow some points first with !borrow.")
                return

            msg = f"Thanks for making a loan payment {user}. You now have {points} points and a remaining debt of {debts} points"
            c.privmsg(self.channel, msg)
            return


    def gamble(self, user, args):
        """
        Process a gamble bet.

        Returns:
            int: Positive for win, negative for loss

        Raises:
            InsufficientPointsError: User has no points
            InvalidBetError: Bet format is invalid
            BetExceedsBalanceError: Bet exceeds available points
        """
        points, debts = self.bank.get_points(user)
        if points == 0:
            raise InsufficientPointsError(f"{user} has no points to gamble")

        bet = None
        if len(args) > 1:
            args = "".join(args)
            if args == "allin":
                bet = points
        if bet is None:
            try:
                bet = int(args[0])
            except IndexError:
                bet = int(random.uniform(1, points+1))
            except ValueError:
                if args[0] == "allin" or args == "allin":
                    bet = points
                else:
                    raise InvalidBetError("Bet must be an integer or 'allin'")

        if bet > points:
            raise BetExceedsBalanceError(f"Bet {bet} exceeds available points {points}")

        win = random.uniform(0, 1) > 0.5
        if win:
            return bet
        else:
            return -1*bet



class GambleBank:

    def __init__(self, db=None):
        logger.debug(f"Initializing GambleBank with db: {db}")
        self.db = db
        self.bank = dict()
        if self.db is not None:
            with open(self.db, 'r') as f:
                self.bank = json.load(f)

    def init_user(self, user):
        if user not in self.bank:
            self.bank[user] = {
                POINTS: DEFAULT_POINTS,
                DEBTS: 0
            }

    def get_points(self, user):
        self.init_user(user)
        return self.bank[user][POINTS], self.bank[user][DEBTS]

    def add_points(self, user, delta_points):
        points, debts = self.get_points(user)
        self.bank[user][POINTS] = max(0, points + delta_points)
        if self.db is not None:
            with open(self.db, 'w') as f:
                json.dump(self.bank, f, indent=4)
        return self.get_points(user)

    def borrow(self, user, loan_amount=DEFAULT_POINTS):
        points, debts = self.get_points(user)
        if points > 0:
            return points, False
        self.bank[user][DEBTS] += loan_amount
        self.bank[user][POINTS] += loan_amount
        if self.db is not None:
            with open(self.db, 'w') as f:
                json.dump(self.bank, f, indent=4)
        return self.get_points(user)

    def payback(self, user):
        """
        Pay back debt with available points.

        Returns:
            tuple: (remaining_points, remaining_debt)

        Raises:
            NoDebtError: User has no debt
            InsufficientPointsError: User has no points to pay back
        """
        points, debts = self.get_points(user)
        if debts == 0:
            raise NoDebtError(f"{user} has no debt to pay back")
        if points == 0:
            raise InsufficientPointsError(f"{user} has no points to pay back debt")

        repayment_amount = min(points, debts)
        self.bank[user][POINTS] -= repayment_amount
        self.bank[user][DEBTS] -= repayment_amount

        if self.db is not None:
            with open(self.db, 'w') as f:
                json.dump(self.bank, f, indent=4)

        return self.get_points(user)

if __name__ == "__main__":
    bank = GambleBank("data/beanBOTbank.json")

    #points, debts = bank.get_points("beanjamin25")
    #print(POINTS, points, DEBTS, debts)
    #bank.add_points("beanjamin25", 24)
    #points, debts = bank.get_points("beanjamin25")
    #print(POINTS, points, DEBTS, debts)

