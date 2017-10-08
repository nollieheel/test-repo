module.exports = function(deployTarget) {
  var ENV = {
    'build': {
      environment: deployTarget
    },
    'revision-data': {
      type: 'git-commit'
    },
    's3-index': {
      accessKeyId: process.env['AWS_ACCESS_KEY_ID'],
      secretAccessKey: process.env['AWS_SECRET_ACCESS_KEY'],
      bucket: 'iflipd-app.iflipd.com',
      region: 'us-west-2',
      allowOverwrite: true
    },
    's3': {
      accessKeyId: process.env['AWS_ACCESS_KEY_ID'],
      secretAccessKey: process.env['AWS_SECRET_ACCESS_KEY'],
      bucket: 'iflipd-app.iflipd.com',
      region: 'us-west-2'
    }
  };

  return ENV;
};
