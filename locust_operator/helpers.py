import os


def is_running_in_cluster():
    """
    Checks to see if the controller is in cluster.
    Useful for features that require on cluster resources such as service routes.
    """
    # TODO should check to see if there is a more robust way of checking this state.
    if os.getenv("KUBERNETES_SERVICE_HOST"):
        return True
    return False


def slower_if_local(interval):
    """
    increase the interval if the operator is running locally.
    x10 increase
    """
    if is_running_in_cluster():
        return interval
    return interval * 10
