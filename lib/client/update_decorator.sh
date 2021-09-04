#!/bin/bash
# This script updates decorator to another version. Version is either the git tag
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


rm -rf /tmp/decorator
git clone https://github.com/micheles/decorator /tmp/decorator

cd /tmp/decorator
git checkout $1
cd $cur_path

git_status=`git status -- decorator | tail -n 1`
git_clean="nothing to commit, working tree clean"

if [[ $git_status == $git_clean ]]; then
    rm -rf decorator/
    mv /tmp/decorator/src/decorator.py .
    echo $1 > decorator_version
else
    echo ""
    echo -e "${red}ERROR"
    echo "There are uncommitted changes or untracked files in './decorator.py'."
    echo ""
    echo -e "${noc}See 'git status -- decorator.py' for more details."
fi

rm -rf /tmp/decorator

