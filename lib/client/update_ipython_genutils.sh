#!/bin/bash
# This script updates ipython_genutils to another version. Version is either the git tag
# or the commit has of the respective release
#
# Usage:
#       ./update_ipython_genutils.sh 4.0.0
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


rm -rf /tmp/ipython_genutils
git clone https://github.com/ipython/ipython_genutils /tmp/ipython_genutils

cd /tmp/ipython_genutils
git checkout $1
cd $cur_path

git_status=`git status -- ipython_genutils | tail -n 1`
git_clean="nothing to commit, working tree clean"

if [[ $git_status == $git_clean ]]; then
    rm -rf ipython_genutils/
    mv /tmp/ipython_genutils/ipython_genutils .

    rm -rf ipython_genutils/testing
    rm -rf ipython_genutils/tests
else
    echo ""
    echo -e "${red}ERROR"
    echo "There are uncommitted changes or untracked files in './ipython_genutils/'."
    echo ""
    echo -e "${noc}See 'git status -- ipython_genutils' for more details."
fi

rm -rf /tmp/ipython_genutils

