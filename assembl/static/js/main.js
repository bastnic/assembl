define([
    "app",
    "jquery",
    "views/lateralMenu",
    "views/ideaList",
    "views/ideaPanel",
    "views/segmentList",
    "views/messageList",
    "views/synthesisPanel",
    "models/user",
    "models/segment",
    "router",
    "socket"
], function(app, $, LateralMenu, IdeaList, IdeaPanel, SegmentList, MessageList, SynthesisPanel, User, Segment, Router, Socket){
    'use strict';

    app.init();

    // The router
    app.router = new Router();

    // The socket
    app.socket = new Socket();
    app.on('socket:open', function(){ $('#onlinedot').addClass('is-online').attr('title', 'online'); });
    app.on('socket:close', function(){ $('#onlinedot').removeClass('is-online').attr('title', 'offline'); });

    // User
    app.users = new User.Collection();
    app.users.on('reset', app.loadCurrentUser);
    app.users.fetchFromScriptTag('users-json');

    // Lateral menu
    // app.lateralMenu = new LateralMenu({el: '#lateralMenu'}).render();
    // $('#assembl-mainbutton').on('click', app.lateralMenu.trigger.bind(app.lateralMenu, 'toggle'));
    // app.getCurrentUser().on('change', app.lateralMenu.render, app.lateralMenu);

    // Idea list
    app.ideaList = new IdeaList({el: '#ideaList', button: '#button-ideaList'});

    // Segment List
    app.segmentList = new SegmentList({el: '#segmentList', button: '#button-segmentList'});
    app.segmentList.segments.on('add change reset', app.ideaList.render, app.ideaList);
    app.segmentList.segments.on('invalid', function(model, error){ alert(error); });
    app.users.on('reset', app.segmentList.render, app.segmentList);
    
    // Idea panel
    app.ideaPanel = new IdeaPanel({el: '#ideaPanel', button: '#button-ideaPanel'}).render();
    app.segmentList.segments.on('change reset', app.ideaPanel.render, app.ideaPanel);
    app.users.on('reset', app.ideaPanel.render, app.ideaPanel);

    // Message
    app.messageList = new MessageList({el: '#messageList', button: '#button-messages'}).render();

    // Synthesis
    app.synthesisPanel = new SynthesisPanel({el: '#synthesisPanel', button: '#button-synthesis', ideas: app.ideaList.ideas });
    app.synthesisPanel.model.fetch({reset: true});

    // Fetching the ideas
    app.ideaList.ideas.fetchFromScriptTag('ideas-json');
    app.segmentList.segments.fetchFromScriptTag('extracts-json');

    // Let the game begins...
    Backbone.history.start({hashChange: false, root: "/" + app.slug });

});
