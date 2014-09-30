#!/usr/bin/env python
# This file should be compatible with both Python 2 and 3.
# If it is not, please file a bug report.

#external imports
import sys
#internal imports
import subuserlib.classes.user, subuserlib.run

##############################################################
helpString = """
Display the command which would be issued to launch Docker if you were to run this subuser.

For example:

    $ subuser dry-run firefox

Will display the command used to launch the subuser firefox.

Please note, this is only a rough approximation for debugging purposes and there is no guarantee that the command displayed here would actually work.
"""

#################################################################################################
def dryRunTestSetup():
  import sys,os,getpass
  os.getuid = lambda: 1000
  getpass.getuser = lambda: "travis"

def dryRun(args):
  """
  Print the command that would have been run if this wasn't a dry run.

  >>> dry_run = __import__("dry-run")
  >>> dry_run.dryRunTestSetup()
  >>> dry_run.dryRun([sys.argv[0]]+["foo"])
  The image will be prepared using the Dockerfile:
  FROM 2
  RUN useradd --uid=1000 travis ;export exitstatus=$? ; if [ $exitstatus -eq 4 ] ; then echo uid exists ; elif [ $exitstatus -eq 9 ]; then echo username exists. ; else exit $exitstatus ; fi
  <BLANKLINE>
  The command to launch the image is:
  docker 'run' '-i' '-t' '--rm' '--workdir=/home/travis/test-home' '-v=/home/travis/test-home/.subuser/homes/foo:/home/travis/test-home:rw' '-e' 'HOME=/home/travis/test-home' '--net=none' '--user=1000' 'imageId' '/usr/bin/foo'
  """
  if len(args) == 1 or {"help","-h","--help"} & set(args):
    print(helpString)
    sys.exit()

  subuserName = args[1]
  argsToPassToImage = args[2:]

  user = subuserlib.classes.user.User()
  if subuserName in user.getRegistry().getSubusers():
    print("The image will be prepared using the Dockerfile:")
    print(subuserlib.run.generateImagePreparationDockerfile(user.getRegistry().getSubusers()[subuserName]))
    print("The command to launch the image is:")
    print(subuserlib.run.getPrettyCommand(user.getRegistry().getSubusers()[subuserName],"imageId",argsToPassToImage))
  else:
    sys.exit(subuserName + " not found.\n"+helpString)

if __name__ == "__main__":
  dryRun(sys.argv)
