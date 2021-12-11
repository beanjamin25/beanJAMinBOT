import json
import random

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
            win = self.gamble(user, args)
            points, debts = self.bank.get_points(user)
            msg = None
            if win is None:
                msg = f"{user}, you don't have any points to gamble. You can borrow more points with !borrow if you want to keep playing!"
            elif win is False:
                msg = "You need to bet an integer number of points!"
            elif win is True:
                msg = f"{user}, you cant bet more points than you have! You can either bet all in with !gamble all in, or bet up to {points} points"
            if msg is not None:
                c.privmsg(self.channel, msg)
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
            payback_result = self.bank.payback(user)
            msg = None
            if payback_result is None:
                msg = f"{user}, you're already debt free, silly! You don't need to pay anything back yet!"
            elif payback_result is False:
                msg = f"{user}, you don't have any points to pay back your debts with! You'll need to borrow some points first with !borrow."

            if msg is not None:
                c.privmsg(self.channel, msg)
                return

            points, debts = payback_result
            msg = f"Thanks for making a loan payment {user}. You now have {points} points and a remaining debt of {debts} points"
            c.privmsg(self.channel, msg)
            return


    def gamble(self, user, args):
        c = self.connection
        points, debts = self.bank.get_points(user)
        if points == 0:
            return None

        if len(args) > 1:
            args = "".join(args)
            if args == "allin":
                bet = points
        try:
            bet = int(args[0])
        except IndexError:
            bet = int(random.uniform(1, points+1))
        except ValueError:
            if args[0] == "allin" or args == "allin":
                bet = points
            else:
                return False
        if bet > points:
            return True

        win = random.uniform(0, 1) > 0.5
        if win:
            return bet
        else:
            return -1*bet



class GambleBank:

    def __init__(self, db=None):
        print(db)
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
        points, debts = self.get_points(user)
        if debts == 0:
            return None
        if points == 0:
            return False

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

