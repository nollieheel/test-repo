#!/bin/bash

set -e

##
## Script settings:
##

# region
aws_region=us-west-2
# bucket name (can contain prefix, without trailing slash)
s3_bucket=cfe-ops-test/exampledir

# basename of file/folder to upload
#file_basename=node_modules
file_basename=test
# root dir where file_basename is located (default is current dir)
file_dirname=.
# contains signature hash of current copy at h3
file_dedup=commit_ref

git_branch=nodejs_packaging

# absolute location of binaries
#bin_aws=/usr/local/bin/aws
bin_aws=aws
bin_tar=/bin/tar
bin_git=/usr/bin/git
##
##

suffix=.npm_to_s3
if [ -f /tmp/*"$suffix" ] ; then
    ( >&2 echo "[ERROR] Another operation might still be in progress" )
    exit 200
fi
tmp_file=$( mktemp --suffix "$suffix" )

cleanup() {
    rm "$tmp_file"
    rm -f "/tmp/${file_dedup}" "/tmp/${file_basename}.tar.gz"
}

get_commitref_s3() {
    "$bin_aws" --region "$aws_region" s3 \
               cp "s3://${s3_bucket}/${file_dedup}" "/tmp/${file_dedup}" || \
    echo none > "/tmp/${file_dedup}"
}

get_commitref_s3
current_commit=$( "$bin_git" show-ref --heads -s "$git_branch" )

if [[ $(cat "/tmp/${file_dedup}") != "$current_commit" ]]; then
    echo "Outdated or different remote copy. Preparing to update."

    if [[ -d "${file_dirname}/${file_basename}" ]] || \
       [[ -f "${file_dirname}/${file_basename}" ]]; then
        # stamp file
        "$bin_git" show-ref --heads -s "$git_branch" > "/tmp/${file_dedup}"
        # tar up the file/dir
        "$bin_tar" -czf "/tmp/${file_basename}.tar.gz" \
                   -C "$file_dirname" "$file_basename"
        # upload to s3
        "$bin_aws" --region "$aws_region" s3 \
                   mv "/tmp/${file_dedup}" "s3://${s3_bucket}/"
        "$bin_aws" --region "$aws_region" s3 \
                   mv "/tmp/${file_basename}.tar.gz" "s3://${s3_bucket}/"
    else
        ( >&2 echo "[ERROR] File not found ${file_dirname}/${file_basename}" )
        cleanup
        exit 1
    fi
else
    echo "Remote copy up-to-date."
fi

cleanup
exit 0
