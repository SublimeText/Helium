#!/bin/bash
# This script updates jupyter_client to another version. Version is either the git tag
# or the commit has of the respective release
#
# Usage:
#       ./update_jupyter_client.sh 4.0.0
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


rm -rf /tmp/jupyter_client
git clone https://github.com/jupyter/jupyter_client /tmp/jupyter_client

cd /tmp/jupyter_client
git checkout $1
cd $cur_path

git_status=`git status -- jupyter_client | tail -n 1`
git_clean="nothing to commit, working tree clean"

if [[ $git_status == $git_clean ]]; then
    rm -rf jupyter_client/
    mv /tmp/jupyter_client/jupyter_client .

    rm -rf jupyter_client/tests
else
    echo ""
    echo -e "${red}ERROR"
    echo "There are uncommitted changes or untracked files in './jupyter_client/'."
    echo ""
    echo -e "${noc}See 'git status -- jupyter_client' for more details."
fi

rm -rf /tmp/jupyter_client

