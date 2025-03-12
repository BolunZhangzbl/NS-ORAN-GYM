# -- Public Imports
import os
import numpy as np

# -- Private Imports

# -- Global Variables


# -- Functions


class ActionMapper:
    def __init__(self, minVal, maxVal):
        # Total number of discrete actions
        self.minVal = minVal
        self.maxVal = maxVal
        self.num_actions = (maxVal - minVal + 1)
        self.actions = list(range(minVal, maxVal+1))

    def idx_to_action(self, idx):
        """
        Map an index to a unique action
        """
        if idx < 0 or idx >= self.num_actions:
            raise ValueError(f"Index {idx} out of valid range [0, {self.num_actions - 1}]")

        return int(self.actions[idx])

    def idx_to_bool_action(self, idx):
        if idx < self.minVal or idx > self.maxVal:
            raise ValueError(f"Action index {idx} is out of range [{self.minVal}, {self.maxVal}]")

            # Convert the integer index to a binary string
        binary_str = format(idx, f"0{7}b")

        # Convert the binary string to a list of boolean values
        return [bool(int(bit)) for bit in binary_str]