
# Standard libary includes
import copy

# External libary includes
import ConfigSpace as CS
import ConfigSpace.hyperparameters as CSH
import ConfigSpace.conditions as CSC

# Internal library includes
from .utils.cs_utils import *
from .utils.exceptions import OptionalDependencyException
from .utils.configuration_space import ControllerConfigurationSpace
from . import sysid
from . import optim
from . import ocp

class ControllerStateError(Exception):
    pass

class Controller:
    def __init__(self, system, check_config_in_cs=False):
        self.system = system
        self.models = []
        self.optimizers = []
        self.ocp_factories = []
        self.model = None
        self.optimizer = None
        self.ocp = None
        self.trajs = None
        self.config = None

        self._check_config_in_cs = check_config_in_cs

    def set_model(self, model):
        self.models = [model]
        
    def set_models(self, models):
        self.models = models[:]

    def add_model(self, model):
        self.models.append(model)

    def set_optimizer(self, optimizer):
        self.optimizers = [optimizer]

    def set_optimizers(self, optimizers):
        self.optimizers = optimizers[:]

    def add_optimizer(self, optimizer):
        self.optimizers.append(optimizer)

    def set_ocp_factory(self, ocp_factory):
        self.ocp_factories = [ocp_factory]

    def set_ocp_factories(self, ocp_factories):
        self.ocp_factories = ocp_factories

    def add_ocp_factory(self, ocp_factory):
        self.ocp_factories.append(ocp_factory)

    def set_ocp(self, ocp):
        self.ocp = ocp

    def set_trajs(self, trajs):
        self.trajs = trajs[:]

    def _add_config_space(self, cs, label, choices):
        choice_hyper = CS.CategoricalHyperparameter(label,
            choices=[choice.name for choice in choices])
        cs.add_hyperparameter(choice_hyper)
        for choice in choices:
            add_configuration_space(cs, choice.name,
                choice.get_config_space(),
                parent_hyperparameter={"parent" : choice_hyper,
                    "value" : choice.name}
                )

    def get_config_space(self):
        if self._check_config_in_cs:
            cs = ControllerConfigurationSpace(self)
        else:
            cs = CS.ConfigurationSpace()
        
        self._add_config_space(cs, "model", self.models)
        self._add_config_space(cs, "optimizer", self.optimizers)
        self._add_config_space(cs, "ocp_factory", self.ocp_factories)

        return cs

    def _get_choice_from_config(self, label, choices, config):
        choice_name = config[label]
        for choice in choices:
            if choice.name == choice_name:
                return choice
        raise ValueError(f"Unrecognized config value for {label}")

    def _get_model_from_config(self, config=None):
        if config is None:
            config = self.config
        return self._get_choice_from_config("model", self.models, config)

    def _get_optimizer_from_config(self, config=None):
        if config is None:
            config = self.config
        return self._get_choice_from_config("optimizer", self.optimizers, config)

    def _get_ocp_factory_from_config(self, config=None):
        if config is None:
            config = self.config
        return self._get_choice_from_config("ocp_factory", self.ocp_factories, config)

    def _get_choice_config(self, label, choices, config):
        choice_name = config[label]
        choice = self._get_choice_from_config(label, choices, config)
        return create_subspace_configuration(config, choice_name, 
            choice.get_config_space(), allow_inactive_with_values=True)

    def _get_model_config(self, config=None):
        if config is None:
            config = self.config
        return self._get_choice_config("model", self.models, config)

    def _get_optimizer_config(self, config=None):
        if config is None:
            config = self.config
        return self._get_choice_config("optimizer", self.optimizers, config)

    def _get_ocp_factory_config(self, config=None):
        if config is None:
            config = self.config
        return self._get_choice_config("ocp_factory", self.ocp_factories, config)

    def get_default_config(self):
        return self.get_config_space().get_default_configuration()

    def set_config(self, config):
        if not self.check_config(config):
            raise ValueError("Controller config is incompatible")
        self.config = copy.deepcopy(config)

    def check_config(self, config, ocp=None):
        if ocp is None:
            ocp = self.ocp
        model = self._get_model_from_config(config)
        model_cfg = self._get_model_config(config)
        model_ptype = model.get_prototype(model_cfg)

        ocp_factory = self._get_ocp_factory_from_config(config)
        ocp_config = self._get_ocp_factory_config(config)
        if not ocp_factory.is_compatible(ocp):
            return False
        ocp_ptype = ocp_factory.get_prototype(ocp_config, ocp)

        optim = self._get_optimizer_from_config(config)
        return optim.is_compatible(model_ptype, ocp_ptype)

    def clear_trajs(self):
        self.trajs = None

    def clear_model(self):
        self.model.clear()

    def clear(self):
        self.reset()
        self.clear_trajs()
        self.clear_model()
        self.mode, self.optimizer, self.ocp_factory = None, None, None

    def clone(self):
        return copy.deepcopy(self)

    def build(self):
        if not self.ocp:
            raise ControllerStateError("Must call set_ocp() before build()")
        if self.model:
            self.clear_model()
        if not self.config:
            self.config = self.get_default_config()
        model = self._get_model_from_config()
        optimizer = self._get_optimizer_from_config()
        ocp_factory = self._get_ocp_factory_from_config()
        if model:
            model.set_config(self._get_model_config())
        else:
            raise ControllerStateError("No model specified.  Please add a model before calling build().")
        if optimizer:
            optimizer.set_config(self._get_optimizer_config())
        else:
            raise ControllerStateError("No optimizer specified.  Please add an optimizer before calling build().")
        if ocp_factory:
            ocp_factory.set_config(self._get_ocp_factory_config())
        if model.trainable:
            if self.trajs:
                model.train(self.trajs)
            else:
                raise ControllerStateError("Specified model requires trajectories.  Please call set_trajs() before build().")
        if ocp_factory and ocp_factory.trainable:
            if self.trajs:
                ocp_factory.train(self.trajs)
            else:
                raise ControllerStateError("Specified OCP Factory requires trajectories.  Please call set_trajs() before build().")

        self.model = model
        self.optimizer = optimizer
        self.ocp_factory = ocp_factory

        self.reset()

    def reset(self):
        self.reset_optimizer()
        self.reset_history()

    def reset_history(self):
        self.model_state = None

    def reset_optimizer(self):
        # Instantiate optimizer and transformed ocp
        if self.ocp_factory:
            self.transformed_ocp = self.ocp_factory(self.ocp)
        else:
            self.transformed_ocp = self.ocp
        self.optimizer.set_model(self.model)
        self.optimizer.set_ocp(self.transformed_ocp)
        self.optimizer.reset()

    def set_history(self, history):
        """
        Provide a prior history of observations for modelling purposes.

        Parameters
        ----------
        history : Trajectory
            History of the system.
        """
        self.model_state = self.model.traj_to_state(history)

    def run(self, obs):
        # Returns control, handles model state updates
        if not self.model or not self.optimizer or not self.transformed_ocp:
            raise ControllerStateError("Must call build() before run()")
        if self.model_state is None:
            self.model_state = self.model.init_state(obs)
        elif not self.last_control is None:
            self.model_state = self.model.update_state(self.model_state, 
                    self.last_control, obs)
        
        control = self.optimizer.run(self.model_state)
        self.last_control = control

        return control

    def get_state(self):
        # Returns pickleable state object
        # combining model and optimizer state
        return {"model_state" : self.model_state,
            "last_control" : self.last_control,
            "optimizer_state" : self.optimizer.get_state()}

    def set_state(self, state):
        # Sets controller (model/optimizer) state
        self.model_state = state["model_state"]
        self.last_control = state["last_control"]
        self.optimizer.set_state(state["optimizer_state"])

class AutoSelectController(Controller):
    """
    A version of the controller which comes with a default selection
    of models, optimizer, and OCP factories.
    """
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._add_models()
        self._add_optimizers()
        self._add_ocp_factories()

    def _add_if_available(self, add_func, module, name):
        if not hasattr(module, name):
            return
        try:
            add_func(getattr(module, name)(self.system))
        except OptionalDependencyException:
            return

    def _add_models(self):
        self._add_if_available(self.add_model, sysid, "MLP")
        self._add_if_available(self.add_model, sysid, "ApproximateGP")
        self._add_if_available(self.add_model, sysid, "SINDy")
        self._add_if_available(self.add_model, sysid, "ARX")
        self._add_if_available(self.add_model, sysid, "Koopman")

    def _add_optimizers(self):
        self._add_if_available(self.add_optimizer, optim, "IterativeLQR")
        self._add_if_available(self.add_optimizer, optim, "MPPI")
        self._add_if_available(self.add_optimizer, optim, "LQR")
        self._add_if_available(self.add_optimizer, optim, "DirectTranscription")

    def _add_ocp_factories(self):
        self._add_if_available(self.add_ocp_factory, ocp, "QuadCostFactory")