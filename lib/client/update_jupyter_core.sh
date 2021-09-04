#!/bin/bash
# This script updates jupyter_core to another version. Version is either the git tag
# or the commit has of the respective release
#
# Usage:
#       ./update_jupyter_core.sh 4.0.0
#
cur_path=`pwd`
red='\033[0;31m'
noc='\033[0m'

if [[ $1 == "" ]]; then
    echo -e "${red}ERROR"
    echo -e "${noc}No version spefified."
    echo ""
    echo "Exiting..."
    exit 1;
fi


rm -rf /tmp/jupyter_core
git clone https://github.com/jupyter/jupyter_core /tmp/jupyter_core

cd /tmp/jupyter_core
git checkout $1
cd $cur_path

git_status=`git status -- jupyter_core`
git_clean=$(echo -e "On branch update_libraries\nnothing to commit, working tree clean\n")

if [[ $git_status == $git_clean ]]; then
    rm -rf jupyter_core/
    mv /tmp/jupyter_core/jupyter_core .
    echo $1 > jupyter_core/version
else
    echo ""
    echo -e "${red}ERROR"
    echo "There are uncommitted changes or untracked files in './jupyter_core/'."
    echo ""
    echo -e "${noc}See 'git status -- jupyter_core' for more details."
fi

rm -rf /tmp/jupyter_core

