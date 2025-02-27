# -*- coding: utf-8 -*-

"""
The DockerDaemon object allows us to communicate with the Docker daemon via the Docker HTTP REST API.
"""

#external imports
import urllib
import tarfile
import os
import tempfile
import fnmatch
import re
import json
import sys
try:
  import httplib
except ImportError:
  import http.client
  httplib = http.client
try:
  import StringIO
except ImportError:
  import io
#internal imports
from subuserlib.classes.userOwnedObject import UserOwnedObject
from subuserlib.classes.uhttpConnection import UHTTPConnection
import subuserlib.docker
import subuserlib.test
from subuserlib.classes.docker.container import Container
import subuserlib.classes.exceptions as exceptions

def archiveBuildContext(archive,relativeBuildContextPath,repositoryFileStructure,excludePatterns,dockerfile=None):
  """
  Archive files from directoryWithDockerfile into the FileObject archive excluding files who's paths(relative to directoryWithDockerfile) are in excludePatterns.
  If dockerfile is set to a string, include that string as the file Dockerfile in the archive.
  """
  def getFileObject(contents):
    """
    Returns a FileObject from the given string. Works with both versions of python.
    """
    return io.BytesIO(contents)

  def addFileFromContents(path,contents,mode=420):
    fileObject = getFileObject(contents)
    tarinfo = tarfile.TarInfo(name=path)
    tarinfo.mode=mode
    fileObject.seek(0, os.SEEK_END)
    tarinfo.size = fileObject.tell()
    fileObject.seek(0)
    contexttarfile.addfile(tarinfo,fileObject)
  # Inspired by and partialy taken from https://github.com/docker/docker-py
  contexttarfile = tarfile.open(mode="w",fileobj=archive)
  if relativeBuildContextPath and repositoryFileStructure:
    def addFolder(folder):
      for filename in repositoryFileStructure.lsFiles(folder):
        filePathRelativeToRepository = os.path.join(folder,filename)
        filePathRelativeToBuildContext = os.path.relpath(filePathRelativeToRepository,relativeBuildContextPath)
        exclude = False
        for excludePattern in excludePatterns:
          if fnmatch.fnmatch(filePathRelativeToBuildContext,excludePattern):
            exclude = True
            break
        if not exclude:
          addFileFromContents(path=filePathRelativeToBuildContext,contents=repositoryFileStructure.readBinary(filePathRelativeToRepository),mode=repositoryFileStructure.getMode(filePathRelativeToRepository))
      for subFolder in repositoryFileStructure.lsFolders(folder):
        addFolder(os.path.join(folder,subFolder))
    addFolder(relativeBuildContextPath)
  # Add the provided Dockerfile if necessary
  if not dockerfile == None:
    addFileFromContents(path="./Dockerfile",contents=dockerfile.encode("utf-8"))
  contexttarfile.close()
  archive.seek(0)

def readAndPrintStreamingBuildStatus(user,response):
  jsonSegmentBytes = b''
  output = b''
  byte = response.read(1)
  while byte:
    jsonSegmentBytes += byte
    output += byte
    byte = response.read(1)
    try:
      lineDict = json.loads(jsonSegmentBytes.decode("utf-8"))
      if lineDict == {}:
        pass
      elif "stream" in lineDict:
        user.registry.log(lineDict["stream"])
      elif "status" in lineDict:
        user.registry.log(lineDict["status"])
      elif "errorDetail" in lineDict:
        raise exceptions.ImageBuildException("Build error:"+lineDict["errorDetail"]["message"]+"\n"+response.read().decode())
      else:
        raise exceptions.ImageBuildException("Build error:"+jsonSegmentBytes.decode("utf-8")+"\n"+response.read().decode("utf-8"))
      jsonSegmentBytes = b''
    except ValueError:
      pass
  output = output.decode("utf-8")
  if not output.strip().startswith("{"):
    user.registry.log(output)
  return output

class DockerDaemon(UserOwnedObject):
  def __init__(self,user):
    self.__connection = None
    self.__imagePropertiesCache = {}
    UserOwnedObject.__init__(self,user)

  def getConnection(self):
    """
     Get an `HTTPConnection <https://docs.python.org/2/library/httplib.html#httplib.HTTPConnection>`_ to the Docker daemon.

     Note: You can find more info in the `Docker API docs <https://docs.docker.com/reference/api/docker_remote_api_v1.13/>`_
    """
    if not self.__connection:
      subuserlib.docker.getAndVerifyExecutable()
      try:
        self.__connection = UHTTPConnection("/run/user/1000/docker.sock")
      except PermissionError as e:
        sys.exit("Permission error (%s) connecting to the docker socket. This usually happens when you've added yourself as a member of the docker group but haven't logged out/in again before starting subuser."% str(e))
    return self.__connection

  def getContainers(self,onlyRunning=False):
    queryParameters =  {'all': not onlyRunning}
    queryParametersString = urllib.parse.urlencode(queryParameters)
    self.getConnection().request("GET","/v1.24/containers/json?"+queryParametersString)
    response = self.getConnection().getresponse()
    if response.status == 200:
      return json.loads(response.read().decode("utf-8"))
    else:
      return []

  def getContainer(self,containerId):
    return Container(self.user,containerId)

  def getImageProperties(self,imageTagOrId):
    """
     Returns a dictionary of image properties, or None if the image does not exist.
    """
    try:
      return self.__imagePropertiesCache[imageTagOrId]
    except KeyError:
      pass
    self.getConnection().request("GET","/v1.24/images/"+imageTagOrId+"/json")
    response = self.getConnection().getresponse()
    if not response.status == 200:
      response.read() # Read the response and discard it to prevent the server from getting locked up: https://stackoverflow.com/questions/3231543/python-httplib-responsenotready
      return None
    else:
      properties = json.loads(response.read().decode("utf-8"))
      self.__imagePropertiesCache[imageTagOrId] = properties
      return properties

  def removeImage(self,imageId):
    self.getConnection().request("DELETE","/v1.24/images/"+imageId)
    response = self.getConnection().getresponse()
    if response.status == 404:
      raise ImageDoesNotExistsException("The image "+imageId+" could not be deleted.\n"+response.read().decode("utf-8"))
    elif response.status == 409:
      raise ContainerDependsOnImageException("The image "+imageId+" could not be deleted.\n"+response.read().decode("utf-8"))
    elif response.status == 500:
      raise ServerErrorException("The image "+imageId+" could not be deleted.\n"+response.read().decode("utf-8"))
    else:
      response.read()

  def build(self,relativeBuildContextPath=None,repositoryFileStructure=None,useCache=True,rm=True,forceRm=True,quiet=False,tag=None,dockerfile=None,quietClient=False):
    """
    Build a Docker image.  If a the dockerfile argument is set to a string, use that string as the Dockerfile.  Returns the newly created images Id or raises an exception if the build fails.

    Most of the options are passed directly on to Docker.

    The quietClient option makes it so that this function does not print any of Docker's status messages when building.
    """
    # Inspired by and partialy taken from https://github.com/docker/docker-py
    queryParameters =  {
      'q': "true" if quiet else "false",
      'nocache': "false" if useCache else "true",
      'rm': "true" if rm  else "false",
      'forcerm': "true" if forceRm else "false"
      }
    if tag:
      queryParameters["t"] = tag
    queryParametersString = urllib.parse.urlencode(queryParameters)
    excludePatterns = []
    if relativeBuildContextPath and repositoryFileStructure:
      dockerignore = "./.dockerignore"
      if repositoryFileStructure.exists(dockerignore):
        exclude = list(filter(bool, repositoryFileStructure.read(dockerignore).split('\n')))
    with tempfile.NamedTemporaryFile() as tmpArchive:
      archiveBuildContext(tmpArchive,relativeBuildContextPath=relativeBuildContextPath,repositoryFileStructure=repositoryFileStructure,excludePatterns=excludePatterns,dockerfile=dockerfile)
      query = "/v1.24/build?"+queryParametersString
      self.user.registry.log(query)
      self.getConnection().request("POST",query,body=tmpArchive)
    try:
      response = self.getConnection().getresponse()
    except httplib.ResponseNotReady as rnr:
      raise exceptions.ImageBuildException(rnr)
    if response.status != 200:
      if quietClient:
        response.read()
      else:
        readAndPrintStreamingBuildStatus(self.user, response)
      raise exceptions.ImageBuildException("Building image failed.\n"
                     +"status: "+str(response.status)+"\n"
                     +"Reason: "+response.reason+"\n")
    if quietClient:
      output = response.read().decode("utf-8")
    else:
      output = readAndPrintStreamingBuildStatus(self.user,response)
    # Now we move to regex code stolen from the official python Docker bindings. This is REALLY UGLY!
    outputLines = output.split("\n")
    search = r'Successfully built ([0-9a-f]+)' #This is REALLY ugly!
    match = None
    for line in reversed(outputLines):
      match = re.search(search, line) #This is REALLY ugly!
      if match:
        break
    if not match:
      raise exceptions.ImageBuildException("Unexpected server response when building image. \n " + output)
    shortId = match.group(1) #This is REALLY ugly!
    return self.getImageProperties(shortId)["Id"]

  def getInfo(self):
    """
    Returns a dictionary of version info about the running Docker daemon.
    """
    self.getConnection().request("GET","/v1.24/info")
    response = self.getConnection().getresponse()
    if not response.status == 200:
      response.read() # Read the response and discard it to prevent the server from getting locked up: https://stackoverflow.com/questions/3231543/python-httplib-responsenotready
      return None
    else:
      return json.loads(response.read().decode("utf-8"))

  def execute(self,args,cwd=None,background=False,backgroundSuppressOutput=True,backgroundCollectStdout=False,backgroundCollectStderr=False):
    """
    Execute the docker client.
    If the background argument is True, return emediately with the docker client's subprocess.
    Otherwise, wait for the process to finish and return the docker client's exit code.
    """
    if background:
      return subuserlib.docker.runBackground(args,cwd=cwd,suppressOutput=backgroundSuppressOutput,collectStdout=backgroundCollectStdout,collectStderr=backgroundCollectStderr)
    else:
      return subuserlib.docker.run(args,cwd=cwd)

class ImageBuildException(Exception):
  pass

class ImageDoesNotExistsException(Exception):
  pass

class ContainerDependsOnImageException(Exception):
  pass

class ServerErrorException(Exception):
  pass

if subuserlib.test.testing:
  from subuserlib.classes.docker.mockDockerDaemon import MockDockerDaemon
  RealDockerDaemon = DockerDaemon
  DockerDaemon = MockDockerDaemon
