class ExecutionProjectError(RuntimeError):
    pass


class RegistryError(ExecutionProjectError):
    pass


class BuildError(ExecutionProjectError):
    pass


class PromotionError(ExecutionProjectError):
    pass


class CapabilityExecutionError(ExecutionProjectError):
    pass


class CliEngineError(ExecutionProjectError):
    pass
