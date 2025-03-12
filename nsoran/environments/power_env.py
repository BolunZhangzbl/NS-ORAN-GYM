# -- Public Imports
import numpy as np
import pandas as pd
from gymnasium import spaces
import logging


# -- Private Imports
from nsoran.base.ns_env import NsOranEnv
from constants import *

# -- Global Variables


# -- Functions

class PowerSavingEng(NsOranEnv):
    def __init__(self, ns3_path:str, scenario_configuration:dict, output_folder:str, optimized:bool, verbose=False,
                 time_factor=0.001, Cf=1.0, lambdaf=0.1):
        """
        Environment specific parameters:
        verbose (bool): enables logging
        time_factor (float): applies convertion from seconds to another multiple (eg. ms). See compute_reward
        Cf (float): Cost factor for handovers. See compute_reward
        lambdaf (float): Decay factor for handover cost. See compute_reward
        """
        super().__init__(ns3_path=ns3_path, scenario='scenario-test', scenario_configuration=scenario_configuration,
                         output_folder=output_folder, optimized=optimized,
                         control_header=['timestamp', 'ueId', 'nrCellId'], log_file='TsActions.txt',
                         control_file='ts_actions_for_ns3.csv')

        self.columns_state = [
            'QosFlow.PdcpPduVolumeDL_Filter',  # Throughput (bytes transmitted at PDCP layer)
            'RRU.PrbUsedDl',                   # Number of scheduled PRBs
            'L1M.RS-SINR.Bin34',               # SINR bin for RLF detection
            'DRB.MeanActiveUeDl',              # Average number of active UEs
            'TB.TotNbrDlInitial.64Qam',        # MAC PDUs with 64QAM
            'TB.ErrTotalNbrDl.1',              # Erroneous DL transmissions (for RLF)
            'CARR.PDSCHMCSDist.Bin1',          # MCS distribution (optional for advanced analysis)
            'DRB.BufferSize.Qos'               # Buffer size (optional for advanced analysis)
        ]
        self.columns_reward = [
            'QosFlow.PdcpPduVolumeDL_Filter',  # Throughput
            'RRU.PrbUsedDl',  # Power consumption (approximated by PRB usage)
            'TB.ErrTotalNbrDl.1',  # Number of UEs in RLF
            'L1M.RS-SINR.Bin34'  # SINR for RLF detection (optional)
        ]
        self.observation_space = spaces.Box(shape=(NUM_GNB, len(self.columns_state)), low=-np.inf, high=np.inf, dtype=np.float64)
        self.action_space = spaces.MultiBinary(int(2**NUM_GNB))

        # Stores the kpms of the previous timestamp (see compute_reward)
        self.previous_df = None
        self.previous_kpms = None

        # Keeps track of last handover time (see compute_reward)
        self.handovers_dict = dict()
        self.verbose = verbose
        if self.verbose:
            logging.basicConfig(filename='reward_ts.log', level=logging.DEBUG, format='%(asctime)s - %(message)s')
        self.time_factor = time_factor
        self.Cf = Cf
        self.lambdaf = lambdaf

    def _compute_action(self, action):
        """
        Pass the actions to the ORAN environment (Sim/Testbed)
        """
        assert len(action) == NUM_GNB

        return action

    def _get_obs(self):
        """
        The state info contains KPMs:
        1. Ratio between throughput and energy consumption at cell i
        2. Number of UEs in RLF at cell i
        3. Percentage of UEs in RLF at cell i
        4. Number of scheduled PRBs at cell i
        5. Percentage of scheduled PRBs at cell i
        6. Number of MAC PDUs with a MCS that uses 64QAM
        7. Number of bytes transmitted at PHY layer
        8. Cost to activate at cell i
        :return:
        """
        ue_kpms = self.datalake.read_kpms(self.last_timestamp, self.columns_state)

        self.observations = np.array(ue_kpms)

        return self.observations

    def _compute_reward(self):
        """
        The total reward is the sum of per gBN reward,
        where per gNB reward = w1*throughput - w2*power_consumption - w3*activeUEs
        """
        pass



