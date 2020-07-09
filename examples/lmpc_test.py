from pdb import set_trace
import sys, os
sys.path.append(os.getcwd() + "/..")

import numpy as np
import autompc as ampc
import matplotlib.pyplot as plt
import matplotlib.animation as animation
from joblib import Memory

from scipy.integrate import solve_ivp

memory = Memory("cache")

pendulum = ampc.System(["ang", "angvel"], ["torque"])

def pendulum_dynamics(y,u,g=9.8,m=1,L=1,b=0.1):
    theta, omega = y
    return [omega,((u[0] - b*omega)/(m*L**2)
        - g*np.sin(theta)/L)]

def dt_pendulum_dynamics(y,u,dt,g=9.8,m=1,L=1,b=0.1):
    y[0] += np.pi
    sol = solve_ivp(lambda t, y: pendulum_dynamics(y, u, g, m, L, b), (0, dt), y, t_eval = [dt])
    if not sol.success:
        raise Exception("Integration failed due to {}".format(sol.message))
    y = sol.y.reshape((2,))
    y[0] -= np.pi
    return sol.y.reshape((2,))

def animate_pendulum(fig, ax, dt, traj):
    ax.grid()

    line, = ax.plot([0.0, 0.0], [0.0, -1.0], 'o-', lw=2)
    time_text = ax.text(0.02, 0.95, '', transform=ax.transAxes)

    def init():
        line.set_data([0.0, 0.0], [0.0, -1.0])
        time_text.set_text('')
        return line, time_text

    def animate(i):
        #i = min(i, ts.shape[0])
        line.set_data([0.0, np.sin(traj[i,"ang"]+np.pi)], 
                [0.0, -np.cos(traj[i,"ang"] + np.pi)])
        time_text.set_text('t={:2f}'.format(dt*i))
        return line, time_text

    ani = animation.FuncAnimation(fig, animate, frames=traj.size, interval=dt*1000,
            blit=False, init_func=init, repeat_delay=1000)

    return ani

dt = 0.025

umin = -2.0
umax = 2.0

# Generate trajectories for training
num_trajs = 100

@memory.cache
def gen_trajs():
    rng = np.random.default_rng(42)
    trajs = []
    for _ in range(num_trajs):
        y = [-np.pi, 0.0]
        traj = ampc.zeros(pendulum, 400)
        for i in range(400):
            traj[i].obs[:] = y
            u = rng.uniform(umin, umax, 1)
            y = dt_pendulum_dynamics(y, u, dt)
            traj[i].ctrl[:] = u
        trajs.append(traj)
    return trajs
trajs = gen_trajs()

from autompc.sysid import ARX, Koopman#, SINDy

def train_koop():
    koop = Koopman(pendulum)
    #koop.set_hypers(basis_functions=set(["trig"]),
    #        method="lasso", lasso_alpha=0.00001)
    koop.set_hypers(basis_functions=set(["trig"]))
    koop.train(trajs)
    return koop


koop = train_koop()

model = koop
from autompc.control.mpc import LQRCost, LinearMPC

Q = np.diag([10.0, 0.5])
R = np.diag([0.01])
cost = LQRCost(Q, R, F=Q)
con = LinearMPC(pendulum, model, cost)
con.horizon.value = 8

sim_traj = ampc.zeros(pendulum, 1)
x = np.array([-np.pi,0.0])
sim_traj[0].obs[:] = x

for _ in range(100):
    u, _ = con.run(sim_traj)
    x = dt_pendulum_dynamics(x, u, dt)
    sim_traj[-1, "torque"] = u
    sim_traj = ampc.extend(sim_traj, [x], [[0.0]])
    xtrans = con.state_func(sim_traj)

#plt.plot(sim_traj[:,"x1"], sim_traj[:,"x2"], "b-o")
#plt.show()

fig = plt.figure()
ax = fig.gca()
ax.set_aspect("equal")
ax.set_xlim([-1.1, 1.1])
ax.set_ylim([-1.1, 1.1])
ani = animate_pendulum(fig, ax, dt, sim_traj)
#ani.save("out/test4/koop_lmpc.mp4")
plt.show()