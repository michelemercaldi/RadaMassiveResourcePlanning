from pmas_configuration import PmasConfiguration
from pmas_strategy import PmasStrategy
from pmas_util import PmasLoggerSingleton


glog = None   # global logger



# ---------------- MAIN ENTRY ---------------- #
if __name__ == "__main__":
    conf = PmasConfiguration()
    glog = PmasLoggerSingleton.get_logger(conf)
    strategy = PmasStrategy(conf)

    glog.info("\n--------------------- simulate user input")
    simulate_user_input = strategy.simulate_user_input()
    glog.info(simulate_user_input)
    glog.info("---------------------\n")

    strategy.exec_simulation_logic(simulate_user_input, None)

