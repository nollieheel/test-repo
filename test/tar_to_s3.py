#!/usr/bin/env python
#
# Pip package dependencies:
#   pyOpenSSL
#   ndg-httpsclient
#   pyasn1
#   boto3
#   pytz

#   subprocess
#

import time
import os
import tempfile
import sys
import boto3
import time
import pytz
import argparse

import subprocess

from datetime import datetime
from botocore.exceptions import ClientError

# Set hardcoded defaults here if desired:
DEF_BASENAME = 'node_modules'
DEF_DIRNAME = './'
DEF_PROFILE = None
DEF_REGION = None
DEF_BUCKET = None


def get_args():
  """
  Just get the default and user-defined values for the script.
  """
  parser = argparse.ArgumentParser(description='Tar up a file/directory ' +
    'and upload to an S3 bucket')

  parser.add_argument('-p', '--profile', help='aws credentials profile to use')
  parser.add_argument('-r', '--region', help='aws region')
  parser.add_argument('-b', '--bucket', help='s3 bucket name')
  parser.add_argument('-d', '--dirname', help='root directory')
  parser.add_argument('-w', '--wait', type=int,
    help='wait time for new instances (> 0, default: {})'.format(DEF_WAIT_TIME))

  args = parser.parse_args()

  profile = args.profile or DEF_PROFILE
  region = args.region or DEF_REGION
  wait = args.wait or DEF_WAIT_TIME
  tempfile = '/tmp/asg-old_{}.instances'.format(
    args.asg_name.replace(' ','-').lower())

  return [args.asg_name, profile, region, wait, tempfile]


def write_instances_to_file(asgclient, asg, tempfile):
  """
  Get the currently healthy ASG instance IDs and
  write them to the temporary file.
  """
  resp = asgclient.describe_auto_scaling_instances()

  old_ins = []
  for x in resp['AutoScalingInstances']:
    if (x['AutoScalingGroupName'] == asg and x['HealthStatus'] == 'HEALTHY'):
      old_ins.append(x['InstanceId'])

  print 'Healthy instances:'
  for i in old_ins: print '  ' + i

  with open(tempfile, 'w') as f: f.writelines([i + "\n" for i in old_ins])


def is_instance_ok(ins):
  """
  Check if the instance exists, and is in either a
  'pending' or 'running' state.
  """
  try:
    state = ins.state['Code']
    if not (state == 0 or state == 16):
      print 'Instance {} state: {}.'.format(ins.instance_id, ins.state['Name'])
      return False
  except (AttributeError, ClientError) as e:
    print 'Instance {} error: {}'.format(ins.instance_id, e)
    return False

  return True


def wait_for_instance(asgclient, ec2resource, iid, wait):
  """
  Wait for an EC2 instance to be confirmed 'running' by AWS,
  then wait for an additional number of seconds just to make sure.

  Return False if instance is either non-existent, or stopped/terminated.
  """
  ins = ec2resource.Instance(iid)

  if is_instance_ok(ins):
    print 'Instance {}. Waiting to run.'.format(iid)
    ins.wait_until_running()

  while True:
    if not is_instance_ok(ins): return False

    elapsed = (datetime.now(pytz.utc) - ins.launch_time).total_seconds()
    if elapsed >= wait: break

    resp = asgclient.describe_auto_scaling_instances(InstanceIds=[iid])
    print 'Instance {} (HealthStatus: {}, LifecycleState: {}): {}s.'.format(
      iid, resp['AutoScalingInstances'][0]['HealthStatus'],
      resp['AutoScalingInstances'][0]['LifecycleState'], elapsed)
    time.sleep(DEF_WAIT_INC)

  return True


def get_new_instances(asgclient, asg, tempfile):
  """
  Returns the list of new (running?) instances besides the ones
  already listed in the temporary file.
  """
  resp = asgclient.describe_auto_scaling_instances()

  cur_ins = []
  for x in resp['AutoScalingInstances']:
    if x['AutoScalingGroupName'] == asg: cur_ins.append(x['InstanceId'])

  try:
    with open(tempfile) as f: old_ins = [i.strip() for i in f.readlines()]
  except IOError as e:
    print 'WARNING: {}'.format(e)
    old_ins = []

  return list(set(cur_ins) - set(old_ins))


def get_wait_for_new_instances(asgclient, ec2resource, asg, tempfile, wait):
  for i in get_new_instances(asgclient, asg, tempfile):
    if not wait_for_instance(asgclient, ec2resource, i, wait):
      print 'Error detected with new instance {}.'.format(i)
      return False

  return True


def terminate_instance(asgclient, ec2resource, iid):
  """
  Terminate an instance that is either 'pending' or 'running'.
  Return True if a terminate request was actually sent.
  """
  ins = ec2resource.Instance(iid)

  if not is_instance_ok(ins): return False

  print 'NOT ACTUALLY terminating instance {}.'.format(iid)
  time.sleep(60)
#  resp = asgclient.terminate_instance_in_auto_scaling_group(
#    InstanceId=iid,
#    ShouldDecrementDesiredCapacity=False
#  )
#  if not resp['ResponseMetadata']['HTTPStatusCode'] == 200:
#    print 'Error during termination request: {}'.format(resp)
#    return False

  return True


def get_newly_born_instance(asgclient, ec2resource, asg, wait):
  """
  Poll the autoscaling group for an instance that is in a 'pending'
  state, indicating that it has just been created and is waiting to run.

  This way of detecting a new instance might be flimsy, but
  it is the only way that I can see right now. It seems to work fine.
  """
  start = datetime.now(pytz.utc)

  while (datetime.now(pytz.utc) - start).total_seconds() < wait:
    resp = asgclient.describe_auto_scaling_instances()

    for x in resp['AutoScalingInstances']:
      if x['AutoScalingGroupName'] == asg:
        ins = ec2resource.Instance(x['InstanceId'])

        if ins.state['Code'] == 0:
          print 'Detected new instance: {}.'.format(x['InstanceId'])
          return x['InstanceId']

    print 'Waiting for a new replacement instance.'
    time.sleep(DEF_WAIT_INC)

  return False


def rolling_terminate(asgclient, ec2resource, wait, asg, iids):
  """
  The actual deploy process.
  For every old instance, terminate it and wait for a replacement.
  """
  if len(iids) == 0: return True

  if terminate_instance(asgclient, ec2resource, iids[0]):
    print 'ok'
#    niid = get_newly_born_instance(asgclient, ec2resource, asg, wait)
#    if not niid:
#      print 'Error detected while waiting for new instance.'
#      return False

#    if not wait_for_instance(asgclient, ec2resource, niid, wait):
#      print 'Error detected with new instance {}.'.format(niid)
#      return False

  return rolling_terminate(asgclient, ec2resource, wait, asg, iids[1:])


def cleanup(tempfile):
  try: os.remove(tempfile)
  except OSError: pass


def abort():
  print 'Aborting run.'
  sys.exit(1)


if __name__ == "__main__":
  asg, profile, region, wait, tempfile = get_args()

  print 'Rolling deploy for autoscaling group "{}".'.format(asg)
  print 'Implementing instance wait time of {} seconds.'.format(wait)
  print 'AWS profile: {}\nAWS region: {}'.format(profile, region)
  print 'Temporary file {}.'.format(tempfile)
  print 'Start: ' + datetime.now(pytz.utc).strftime('%Y %b %d, %I:%M%p %Z')

  if not profile:
    if not region:
      boto3.setup_default_session()
    else:
      boto3.setup_default_session(region_name=region)
  else:
    if not region:
      boto3.setup_default_session(profile_name=profile)
    else:
      boto3.setup_default_session(profile_name=profile, region_name=region)

  asgclient = boto3.client('autoscaling')
  ec2resource = boto3.resource('ec2')

  if not os.path.isfile(tempfile):
    write_instances_to_file(asgclient, asg, tempfile)

  with open(tempfile) as f: instances = [s.strip() for s in f.readlines()]

  if not get_wait_for_new_instances(
    asgclient, ec2resource, asg, tempfile, wait
  ):
    abort()

  if not rolling_terminate(
    asgclient, ec2resource, wait, asg, instances
  ):
    abort()

  cleanup(tempfile)

  print 'Rolling deploy for autoscaling group "{}" done.'.format(asg)
  print 'End: ' + datetime.now(pytz.utc).strftime('%Y %b %d, %I:%M%p %Z')
  sys.exit(0)
