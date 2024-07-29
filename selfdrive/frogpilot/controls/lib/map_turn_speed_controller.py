# PFEIFER - MTSC
import json
import math

from openpilot.common.conversions import Conversions as CV
from openpilot.common.numpy_fast import interp
from openpilot.common.params import Params

params_memory = Params("/dev/shm/params")

R = 6373000.0  # approximate radius of Earth in meters
TO_RADIANS = math.pi / 180
TARGET_ACCEL = -1.2  # m/s^2 should match up with the long planner
TARGET_OFFSET = 1.0  # seconds - This controls how soon before the curve you reach the target velocity. It also helps
                     # reach the target velocity when innacuracies in the distance modeling logic would cause overshoot.
                     # The value is multiplied against the target velocity to determine the additional distance. This is
                     # done to keep the distance calculations consistent but results in the offset actually being less
                     # time than specified depending on how much of a speed diffrential there is between v_ego and the
                     # target velocity.

def calculate_accel(t, target_jerk, a_ego):
  return a_ego + target_jerk * t

def calculate_velocity(t, target_jerk, a_ego, v_ego):
  return v_ego + a_ego * t + target_jerk / 2 * (t ** 2)

def calculate_distance(t, target_jerk, a_ego, v_ego):
  return t * v_ego + a_ego / 2 * (t ** 2) + target_jerk / 6 * (t ** 3)

def distance_to_point(ax, ay, bx, by):
  a = (math.sin((bx - ax) / 2) ** 2 + math.cos(ax) * math.cos(bx) * math.sin((by - ay) / 2) ** 2)
  c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
  return R * c  # in meters

class MapTurnSpeedController:
  def __init__(self):
    self.target_lat = 0.0
    self.target_lon = 0.0
    self.target_v = 0.0

  def target_speed(self, v_ego, a_ego) -> float:
    try:
      position = json.loads(params_memory.get("LastGPSPosition"))
      lat = position["latitude"]
      lon = position["longitude"]
    except:
      return 0.0

    try:
      target_velocities = json.loads(params_memory.get("MapTargetVelocities"))
    except:
      return 0.0

    min_dist, min_idx = float('inf'), 0
    distances = [distance_to_point(lat * TO_RADIANS, lon * TO_RADIANS, tv["latitude"] * TO_RADIANS, tv["longitude"] * TO_RADIANS) for tv in target_velocities]

    for i, d in enumerate(distances):
      if d < min_dist:
        min_dist = d
        min_idx = i

    forward_points = target_velocities[min_idx:]
    forward_distances = distances[min_idx:]

    valid_velocities = []
    for i, target_velocity in enumerate(forward_points):
      tv = target_velocity["velocity"]
      if tv > v_ego:
        continue

      d = forward_distances[i]
      a_diff = a_ego - TARGET_ACCEL
      accel_t = abs(a_diff / TARGET_JERK)
      min_accel_v = calculate_velocity(accel_t, TARGET_JERK, a_ego, v_ego)

      max_d = 0
      if tv > min_accel_v:
        a, b, c = 0.5 * TARGET_JERK, a_ego, v_ego - tv
        t = max(((b**2 - 4 * a * c) ** 0.5 - b) / (2 * a), ((b**2 - 4 * a * c) ** 0.5 + b) / (2 * a))
        if isinstance(t, complex) or t < 0:
          continue
        max_d += calculate_distance(t, TARGET_JERK, a_ego, v_ego)
      else:
        max_d += calculate_distance(accel_t, TARGET_JERK, a_ego, v_ego)
        t = abs((min_accel_v - tv) / TARGET_ACCEL)
        max_d += calculate_distance(t, 0, TARGET_ACCEL, min_accel_v)

      if d < max_d + tv * TARGET_OFFSET:
        valid_velocities.append((float(tv), target_velocity["latitude"], target_velocity["longitude"]))

    min_v = 100.0
    target_lat = 0.0
    target_lon = 0.0
    for tv, tlat, tlon in valid_velocities:
      if tv < min_v:
        min_v, target_lat, target_lon = tv, tlat, tlon

    if self.target_v < min_v and (self.target_lat or self.target_lon):
      for target_velocity in forward_points:
        if (target_velocity["latitude"], target_velocity["longitude"], target_velocity["velocity"]) == (self.target_lat, self.target_lon, self.target_v):
          return float(self.target_v)
      self.target_v = 0.0
      self.target_lat = 0.0
      self.target_lon = 0.0

    self.target_v = min_v
    self.target_lat = target_lat
    self.target_lon = target_lon

    return min_v
