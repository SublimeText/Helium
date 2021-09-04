#!/bin/bash
# This script updates traitlets to another version. Version is either the git tag
# or the commit has of the respective release
#
# Usage:
#       ./update_traitlets.sh 4.0.0
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


rm -rf /tmp/traitlets
git clone https://github.com/ipython/traitlets /tmp/traitlets

cd /tmp/traitlets
git checkout $1
cd $cur_path

git_status=`git status -- traitlets | tail -n 1`
git_clean="nothing to commit, working tree clean"

if [[ $git_status == $git_clean ]]; then
    rm -rf traitlets/
    mv /tmp/traitlets/traitlets .

    rm -rf traitlets/tests
    rm -rf traitlets/config/tests
else
    echo ""
    echo -e "${red}ERROR"
    echo "There are uncommitted changes or untracked files in './traitlets/'."
    echo ""
    echo -e "${noc}See 'git status -- traitlets' for more details."
fi

rm -rf /tmp/traitlets

