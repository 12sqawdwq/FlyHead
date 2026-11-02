"""FlyHead: a whole-brain fruit-fly connectome driving a wheel-legged robot.

Subpackages are deliberately independent; importing one never loads torch or ROS unless it needs them.
  fly         connectome model, stimulus encoders, motor decoders, brain service   (GPU host)
  safety      command envelope: may only reduce or zero a command
  slam        LiDAR odometry, relocalization, map layers, raw recordings
  navigation  route planning and following
  server      control server: robot session, control loop, brain link              (compute host)
  sim         closed-loop simulations and a synthetic arena
  monitor     operator web console                                                  (operator PC)
The robot-side bridge lives in robot/ and does not import this package.
"""
__version__ = '0.1.0'
