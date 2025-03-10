from abc import abstractmethod
import sem
import pprint
import fcntl
import selectors
import time
from typing import Any, SupportsFloat
import uuid
import gymnasium as gym
import os
import glob
import csv
from posix_ipc import Semaphore, O_CREAT, BusyError
from .action_controller import ActionController
from .datalake import SQLiteDatabaseAPI
from importlib.machinery import SourceFileLoader
import types
import subprocess

class NsOranEnv(gym.Env):
    """Base abstract class for a ns-O-RAN enviroment compliant with Gymnasium"""
    metadata = {'render_modes': ['ansi']}
    ns3_path: str
    scenario : str  
    scenario_configuration: dict
    output_folder: str
    optimized : bool
    skip_configuration : bool
    sim_path : str
    sim_process : subprocess.Popen
    metricsReadySemaphore : Semaphore
    controlSemaphore : Semaphore
    control_header : list
    log_file: str
    control_file: str
    is_open: bool
    action_controller: ActionController
    datalake: SQLiteDatabaseAPI

    def __init__(self, render_mode:str=None, ns3_path:str=None, scenario:str=None, scenario_configuration:dict=None, output_folder:str=None,
                 optimized:bool=True, skip_configuration:bool=False, control_header: list = [], log_file: str = '', control_file: str = ''):
        """Initialize environment 
        Args:
            render_mode (str): Select one of the render modes available.
            ns3_path (str): Path to the ns-3 folder.
            scenario (str): Name of the simulation scenario to be executed.
            scenario_configuration (dict): Dictionary containing the attributes of the simulation scenario.
            output_folder (str): Output folder for the simulation data.
            optimized (bool): If set, the environment will run ns-3 in an optimized mode.
            skip_configuration (bool): If set, the environment will skip the configuration phase.
            control_header (list): list of features that composes the control action specific to the use case.
            log_file (str): name of the file that saves the action generated by the agent in the simulation output folder.
            control_file (str): name of the file that delivers the action generated by the agent to the simulation.
        """

        if render_mode and render_mode not in self.metadata['render_modes']:
            raise ValueError(f'{render_mode} is not a valid render mode. Values accepted are: {self.metadata["render_modes"]}')
        self.render_mode = render_mode

        self.ns3_path = ns3_path
        self.scenario = scenario            
        self.scenario_configuration = {k: v[0] for k, v in scenario_configuration.items() if v}
        self.output_folder = output_folder
        self.optimized = optimized
        self.skip_configuration = skip_configuration
        self.control_header = control_header
        self.log_file = log_file
        self.control_file = control_file

        self.is_open = False
        self.return_info = False

        self.setup_sim()
        print("\nsetup_sim finished!")
    
    def setup_sim(self):
        """Setup all the relevant parameters to configure, compile and execute the simulation.
           This should be called once and it is mostly taken from sem.runner.SimulationRunner::__init__().
        """
        if self.optimized:
            # For old ns-3 installations, the library is in build, while for
            # recent ns-3 installations it's in build/lib. Both paths are
            # thus required to support all versions of ns-3.
            library_path = "%s:%s" % (
                os.path.join(self.ns3_path, 'build/optimized'),
                os.path.join(self.ns3_path, 'build/optimized/lib'))
        else:
            library_path = "%s:%s" % (
                os.path.join(self.ns3_path, 'build/'),
                os.path.join(self.ns3_path, 'build/lib'))
        
        # We use both LD_ and DYLD_ to support Linux and Mac OS.
        self.environment = {
            'LD_LIBRARY_PATH': library_path,
            'DYLD_LIBRARY_PATH': library_path}
        
        # Configure and build ns-3
        # print('Start configuration')
        self.configure_and_build_ns3()
        # print('Configuration complete')

        # ns-3's build status output is used to get the executable path for the
        # specified script.
        if os.path.exists(os.path.join(self.ns3_path, "ns3")):
            # In newer versions of ns-3 (3.36+), the name of the build status file is 
            # platform-dependent
            build_status_fname = ".lock-ns3_%s_build" % os.sys.platform
            build_status_path = os.path.join(self.ns3_path, build_status_fname)
        else:
            build_status_fname = "build.py"
            if self.optimized:
                build_status_path = os.path.join(self.ns3_path,
                                                'build/optimized/build-status.py')
            else:
                build_status_path = os.path.join(self.ns3_path,
                                                'build/build-status.py')

        # By importing the file, we can naturally get the dictionary
        loader = SourceFileLoader(build_status_fname, build_status_path)
        mod = types.ModuleType(loader.name)
        loader.exec_module(mod)
        
        # Search is simple: we look for the script name in the program field.
        # Note that this could yield multiple matches, in case the script name
        # string is contained in another script's name.
        # matches contains [program, path] for each program matching the script
        matches = [{'name': program,
                    'path': os.path.abspath(os.path.join(self.ns3_path, program))} for
                   program in mod.ns3_runnable_programs if self.scenario
                   in program]

        if not matches:
            raise ValueError(f"Cannot find {self.scenario} script")

        # To handle multiple matches, we take the 'better matching' option,
        # i.e., the one with length closest to the original script name.
        match_percentages = map(lambda x: {'name': x['name'],
                                           'path': x['path'],
                                           'percentage':
                                           len(self.scenario)/len(x['name'])},
                                matches)

        self.script_executable = max(match_percentages, key=lambda x: x['percentage'])['path']

        # This step is not needed for CMake versions of ns-3
        if "scratch" in self.script_executable and not os.path.exists(os.path.join(self.ns3_path, "ns3")):
            path_with_subdir = self.script_executable.split("/scratch/")[-1]
            if "/" in path_with_subdir:  # Script is in a subdir
                executable_subpath = "%s/%s" % (self.scenario, self.scenario)
            else:  # Script is in scratch root
                executable_subpath = self.scenario

            if self.optimized:
                self.script_executable = os.path.abspath(
                    os.path.join(self.ns3_path,
                                 "build/optimized/scratch",
                                 executable_subpath))
            else:
                self.script_executable = os.path.abspath(
                    os.path.join(self.ns3_path,
                                 "build/scratch",
                                 executable_subpath))

    def configure_and_build_ns3(self):
        """
        Configure and build the ns-3 code, the code is taken from sem.runner.SimulationRunner::configure_and_build().
        """  
        build_program = "./ns3" if os.path.exists(os.path.join(self.ns3_path, "ns3")) else "./waf"

        # Only configure if necessary
        if not self.skip_configuration:
            configuration_command = ['python3', build_program, 'configure',
                                     '--enable-examples', '--disable-gtk',
                                     '--disable-werror']

            if self.optimized:
                configuration_command += ['--build-profile=optimized',
                                          '--out=build/optimized']

            # Check whether path points to a valid installation
            subprocess.run(configuration_command, cwd=self.ns3_path, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)

        # Build ns-3
        # We don't care about the progress bar of the SimulationRunner, thus we use subprocess.run and wait the build to end
        j_argument = ['-j', str(os.cpu_count())] # if this makes problems just cut it
        subprocess.run(['python3', build_program] + j_argument + ['build'],
                                         cwd=self.ns3_path, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
        print(f"\nself.ns3_path: {self.ns3_path}")

    def start_sim(self):
        """
            Start the ns-3 simulation and all the entities to manage the control, i.e.,:
                1 - Create simulation folder inside the output folder chosen by the user.
                2 - Create Datalake and Action Controller.
                3 - Create the Semaphores.
                4 - Start the Simulation.
        """
        if self.is_open:
            raise ValueError('The environment is open and a new start_sim has been called.')

        self.is_open = True
        # We may need to explicit the default values as well here, but for the moment we only change the values of the configuration
        # A good way would be to explict such values is to port here sem.manager.CampaignManager::check_and_fill_parameters
        parameters = self.scenario_configuration
        print("parameters (scenario configuration): ")
        pprint.pprint(parameters)
        
        # sem.CampaignManager.check_and_fill_parameters()

        ### Create simulation folder inside the output folder chosen by the user, mostly taken from sem.runner.SimulationRunner::run_simulations() ###
        self.sim_result = { 'params': {}, 'meta': {} }
        self.sim_result['params'].update(parameters)

        command = [self.script_executable] + ['--%s=%s' % (param, value) for param, value in parameters.items()]
        
        # Run from dedicated self.sim_path folder
        sim_uuid = str(uuid.uuid4())
        self.sim_result['meta']['id'] = sim_uuid
        self.sim_path = os.path.join(self.output_folder, self.sim_result['meta']['id'])
        os.makedirs(self.sim_path)

        ### End create simulation folder ###

        ### Create Datalake and Action Controller ###

        if not self.log_file:
            raise ValueError('Missing the log file path.')

        if not self.control_file:
            raise ValueError('Missing the control file path.')

        if not self.control_header:
            raise ValueError('Missing the list of values to perform control.')
        
        print(f"\nself.sim_path: {self.sim_path}")
        self.action_controller = ActionController(self.sim_path, self.log_file, self.control_file, self.control_header)
        self.datalake = SQLiteDatabaseAPI(self.sim_path, num_ues_gnb=self.sim_result['params']['ues'])
        pprint.pprint(self.datalake.__dict__)
        # print(f"\nself.datalake: {self.datalake.__dict__}")

        ### End Datalake and Action Controller ###

        ### Create the Semaphores ###

        nameMetricsReadySemaphore = "/sem_metrics_" + self.sim_path.split('/')[-1]
        nameControlSemaphore = "/sem_control_" + self.sim_path.split('/')[-1]
        self.metricsReadySemaphore = Semaphore(nameMetricsReadySemaphore, O_CREAT, 0)
        self.controlSemaphore = Semaphore(nameControlSemaphore, O_CREAT, 0)
        self.last_timestamp = 0

        # print()
        # print(nameControlSemaphore)
        # print(nameMetricsReadySemaphore)
        
        ### End create the Semaphores ###
        
        ### Launch simulation ###
       
        # launch the simulation with the wanted configuration
        # Store process id or whatever reference we can use for the simulation
        
        self.sim_result['meta']['start_time'] = time.time()

        print(f"\ncommand: {command}")
        self.sim_process = subprocess.Popen(command, cwd=self.sim_path, env=self.environment,
                                        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

        # Register the stdout and stderr file descriptors with the selector
        self.selector = selectors.DefaultSelector()

        # Set non-blocking mode for stdout and stderr
        self._set_nonblocking(self.sim_process.stdout)
        self._set_nonblocking(self.sim_process.stderr)

        self.selector.register(self.sim_process.stdout, selectors.EVENT_READ)
        self.selector.register(self.sim_process.stderr, selectors.EVENT_READ)
        ### End create simulation ###

    @staticmethod
    def _set_nonblocking(fileobj):
        """Function to set non-blocking mode a fileobject. This ensures that the select() and read() of I/O are not blocking
        """
        fd = fileobj.fileno()
        flags = fcntl.fcntl(fd, fcntl.F_GETFL)
        fcntl.fcntl(fd, fcntl.F_SETFL, flags | os.O_NONBLOCK)
        
    def read_streams(self):
        events = self.selector.select(timeout=0)  # Non-blocking check
        
        stdout_file_path = os.path.join(self.sim_path, 'stdout')
        stderr_file_path = os.path.join(self.sim_path, 'stderr')
        
        with open(stdout_file_path, 'w+') as stdout_file, open(
                stderr_file_path, 'w+') as stderr_file:
            for key, _ in events:
                data = key.fileobj.read()
                if not data:
                    continue               
                if key.fileobj is self.sim_process.stdout:
                    stdout_file.write(data.strip())
                elif key.fileobj is self.sim_process.stderr:
                    stderr_file.write(data.strip())
    
    def is_simulation_over(self) -> bool:
        """Checks whether the simulation is over or not.
        """
        self.read_streams()
        if self.sim_process.poll() is None:
            return False

        # Ensure any remaining output is processed
        self.read_streams()

        end = time.time()
        return_code = self.sim_process.returncode

        if return_code != 0:
            # The environment should return truncated.
            self.terminated = False
            self.truncated = True

            stdout_file_path = os.path.join(self.sim_path, 'stdout')
            stderr_file_path = os.path.join(self.sim_path, 'stderr')

            with open(stdout_file_path, 'r') as stdout_file, open(
                        stderr_file_path, 'r') as stderr_file:
                complete_command = sem.utils.get_command_from_result(self.scenario, self.sim_result)
                complete_command_debug = sem.utils.get_command_from_result(self.scenario, self.sim_result, debug=True)
                error_message = (f'\nSimulation exited with an error.\nStderr: {stderr_file.read()}\n'
                                    f'Stdout: {stdout_file.read()}\nUse this command to reproduce:\n{complete_command}\n'
                                    f'Debug with gdb:\n{complete_command_debug}')
                
                print(error_message) 
        else:
            # The environment should return terminated and truncated since it is a time limit imposed
            self.terminated = True
            self.truncated = True

        self.sim_result['meta']['elapsed_time'] = end - self.sim_result['meta']['start_time'] 
        self.sim_result['meta']['exitcode'] = return_code
        
        return True

    def reset(self, *, seed: int | None = None, options: dict[str, Any] | None = None):
        super().reset(seed=seed)
        self.start_sim()
        self.close()
        print("Finished start_sim!")
        print(f"self.is_open: {self.is_open}")
        if options:
            if 'return_info' in options:
                self.return_info = options['return_info']
            else:
                self.return_info = False
        else:            # Set here all the default settings
            self.return_info = False

        # The simulation is started, thus we have to wait to the first set of observations
        print("Start metricsReadySemaphore.acquire ......")
        self.metricsReadySemaphore.acquire()
        print("Finished metricsReadySemaphore.acquire")
        self._fill_datalake()
        print("Finished _fill_datalake")

        self.terminated = False
        self.truncated = False
        print("Start _get_obs, render......")
        # The Action is computed in the step, thus the control semaphore is not released
        return (self._get_obs(), self.render()) if self.return_info else (self._get_obs(), {})

    def step(self, action: object) -> tuple[object, SupportsFloat, bool, bool, dict[str, Any]]:
        # Simulation is open in Gym, but it can be terminated in ns-3
        if not self.is_simulation_over():
            # Take a step in the environment based on the given action
            actions = self._compute_action(action)
            print(f"actions: {actions}")

            # Update the environment state and calculate the reward
            self.action_controller.create_control_action(self.last_timestamp, actions)
            # the action was written: notify the environment
            self.controlSemaphore.release()
            
            # Wait for the new metrics to be available
            is_still_active = True
            while is_still_active:
                try:
                    self.metricsReadySemaphore.acquire(timeout=10)
                    break
                except BusyError: # The timeout has elapsed, so we need to check again whether the simulation is over or not
                    is_still_active = not self.is_simulation_over()
            
            self._fill_datalake()
        
        if self.return_info:
            return_tuple = (self._get_obs(), self._compute_reward(), self.terminated, self.truncated, self.render()) 
        else:
            return_tuple = (self._get_obs(), self._compute_reward(), self.terminated, self.truncated, {})

        return return_tuple
    
    def _fill_datalake(self):
        """Helper function that collects from the csv files the latest kpms and uploads them in the Datalake
        """
        self.datalake.acquire_connection()
        for file_path in glob.glob(os.path.join(self.sim_path, 'cu-up-cell-*.txt')):
            with open(file_path, 'r') as csvfile:
                for row in csv.DictReader(csvfile):
                    timestamp = int(row['timestamp'])
                    if timestamp >= self.last_timestamp:
                        cellId = self.datalake.extract_cellId(file_path)
                        row['cellId'] = cellId
                        if cellId == 1:
                            self.datalake.insert_lte_cu_up(row)
                        else:
                            self.datalake.insert_gnb_cu_up(row)
                        self.last_timestamp = timestamp

        for file_path in glob.glob(os.path.join(self.sim_path, 'cu-cp-cell-*.txt')):            
            with open(file_path, 'r') as csvfile:
                for row in csv.DictReader(csvfile):
                    timestamp = int(row['timestamp'])
                    if timestamp >= self.last_timestamp:
                        cellId = self.datalake.extract_cellId(file_path)
                        row['cellId'] = cellId
                        if cellId == 1:
                            self.datalake.insert_lte_cu_cp(row)
                        else:
                            self.datalake.insert_gnb_cu_cp(row)
                        self.last_timestamp = timestamp

        for file_path in glob.glob(os.path.join(self.sim_path, 'du-cell-*.txt')):     
            with open(file_path, 'r') as csvfile:
                for row in csv.DictReader(csvfile):
                    timestamp = int(row['timestamp'])
                    if timestamp >= self.last_timestamp:
                        self.datalake.insert_du(row)
                        self.last_timestamp = timestamp
        
        self._fill_datalake_usecase()
        
        self.datalake.release_connection()

    @abstractmethod
    def _compute_action(self, action) -> list[tuple]:
        """Helper function that converts the agents action defined in Gym into the ns-O-RAN required format according to the use case"""
        raise NotImplementedError('_compute_action() must be implemented for the specific use case')

    @abstractmethod
    def _get_obs(self) -> list:
        """Helper function that returns the curret observation according to the use case"""
        raise NotImplementedError('_get_obs() must be implemented for the specific use case')
    
    @abstractmethod
    def _compute_reward(self):
        """Helper function that returns the curret reward function according to the use case"""
        raise NotImplementedError('_compute_reward() must be implemented for the specific use case')
    
    @abstractmethod
    def _fill_datalake_usecase(self):
        """Function to be implemented by children to add more data
            This function is optional, thus it does not raise an exception.
        """
        pass

    def _get_info(self):
        # TODO deliver last timestamp and time elapsed in the simulation
        return {'isopen': self.is_open, 'results': self.sim_result}
    
    def render(self):
        if self.render_mode == "ansi":
            infos = self._get_info()
            print(infos)
            return infos 
   
    def close(self):
        super().close()
        if self.is_open:
            # TODO save sim_result in the folder
            self.metricsReadySemaphore.release()
            print("metricsReadySemaphore.release() executed!")
            self.sim_process.kill()
            self.controlSemaphore.unlink()
            self.metricsReadySemaphore.unlink()
            self.is_open = False 

    def __del__(self):
        if self.is_open:
            self.close()
