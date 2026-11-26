"""Cross-axis inertial correction for the six-drive BAM FB public model."""

import numpy as np


def move_basis(position, velocity, acceleration):
    # The closed five-bar couples J2 and C1. Terms vanish at rest so the stop's load fit is unchanged.
    relative = position[:, 1] - position[:, 2]
    trigonometry = np.column_stack((np.ones(len(position)), np.cos(relative), np.sin(relative)))
    inertial = acceleration[:, 1:3, None] * trigonometry[:, None, :]
    centripetal = velocity[:, 1:3, None] ** 2 * trigonometry[:, None, :]
    cross_speed = velocity[:, 1] * velocity[:, 2]
    return np.column_stack((inertial.reshape(len(position), -1), centripetal.reshape(len(position), -1), cross_speed))


def features(position, velocity, acceleration):
    coupling = move_basis(position, velocity, acceleration)
    return np.broadcast_to(coupling[:, None, :], (len(position), 6, coupling.shape[1]))
