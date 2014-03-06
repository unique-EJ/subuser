#!/usr/bin/env python
# This file should be compatible with both Python 2 and 3.
# If it is not, please file a bug report.
import os
import sys
import inspect
import permissions
import json
import config
import repositories

home = os.path.expanduser("~") 

def getSubuserDir():
  """ Get the toplevel directory for subuser. """
  return os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(inspect.getfile(inspect.currentframe())))))) # BLEGH!

def getRepoPaths():
  """
  Return a list of paths to the subuser repositories.
  """
  try:
    _repositories = repositories.getRepositories()
    repoPaths = []
    for repo,info in _repositories.iteritems():
      repoPaths.append(info["path"])
    return repoPaths
  except KeyError:
    print("Looking up repo-paths failed. Your repositories.json file is invalid.")
    sys.exit(1)

def getProgramSrcDir(programName):
  """
  Get the directory where the "source" of the application is stored.  That is the permissions list and the docker-image directory.

Returns None if the program cannot be found.

  """
  for repoPath in getRepoPaths():
   programSourceDir = os.path.join(repoPath,programName)
   if os.path.exists(programSourceDir):
     return programSourceDir
  return None

def getExecutablePath(progName):
  """
  Get the path to the executable that we will be installing.
  """
  return os.path.join(config.getConfig()["bin-dir"],progName)

def getPermissionsFilePath(programName):
  """ Return the path to the given programs permissions file.
Returns None if no permission file is found.
 """
  userPermissionsPath = os.path.join(config.getConfig()["user-set-permissions-dir"],programName,"permissions.json")
  if os.path.exists(userPermissionsPath):
    return userPermissionsPath
  else:
    repoPaths = getRepoPaths()
    for repoPath in repoPaths:
      permissionsPath = os.path.join(repoPath,programName,"permissions.json")
      if os.path.exists(permissionsPath):
        return permissionsPath
  return None

def getProgramRegistryPath():
  """ Return the path to the list of installed programs json file. """
  return config.getConfig()["installed-programs.json"]

def getProgramHomeDirOnHost(programName):
  """ Each program has it's own home directory(or perhaps a shared one).
          This directory has two absolute paths:
            The path to the directory as it appears on the host machine,
            and the path to the directory in the docker container.
          Return the path to the directory as it appears on the host macine. """
  programPermissions = permissions.getPermissions(programName)
  sharedHome = permissions.getSharedHome(programPermissions)
  if sharedHome:
    return os.path.join(config.getConfig()["program-home-dirs-dir"],sharedHome)
  else:
    return os.path.join(config.getConfig()["program-home-dirs-dir"],programName)

def getDockersideScriptsPath():
  return os.path.join(getSubuserDir(),"logic","dockerside-scripts")

def getBuildImageScriptPath(programSrcDir):
  """
  Get path to the BuildImage.sh. From the program's docker-image directory.
  """
  return os.path.join(programSrcDir,"docker-image","BuildImage.sh")

def getDockerfilePath(programSrcDir):
  """
  Get path to the Dockerfile From the program's docker-image directory.
  """
  return os.path.join(programSrcDir,"docker-image","Dockerfile")
