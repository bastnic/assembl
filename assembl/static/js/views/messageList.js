define(['backbone', 'underscore', 'zepto', 'app', 'views/messageListItem', 'views/message', 'models/message'],
function(Backbone, _, $, app, MessageListItem, MessageView, Message){
    'use strict';

    var MESSAGE_MODE = 'is-message-mode';

    /**
     * @class views.MessageList
     */
    var MessageList = Backbone.View.extend({
        /**
         *  @init
         */
        initialize: function(obj){
            if( obj.button ){
                this.button = $(obj.button).on('click', app.togglePanel.bind(window, 'messageList'));
            }

            this.messages.on('reset', this.render, this);
            this.messageThread.on('reset', this.renderThread, this);
        },

        /**
         * Flag whether it is being selected or not
         * @type {Boolean}
         */
        isSelecting: false,

        /**
         * The template
         * @type {_.template}
         */
        template: app.loadTemplate('messageList'),

        /**
         * The view's data
         * @type {Object}
         */
        data: {},

        /**
         * The collapse/expand flag
         * @type {Boolean}
         */
        collapsed: true,

        /**
         * The collection
         * @type {MessageCollection}
         */
        messages: new Message.Collection(),

        /**
         * The current message thread
         * @type {MessageCollection}
         */
        messageThread: new Message.Collection(),

        /**
         * The render function
         * @return {views.Message}
         */
        render: function(){
            var list = document.createDocumentFragment(),
                messages = this.messages.where({parentId: null});

            _.each(messages, function(message){
                var messageListItem = new MessageListItem({model:message});
                list.appendChild(messageListItem.render().el);
            });

            var data = {
                page: this.data.page,
                maxPage: this.data.maxPage,
                inbox: this.data.inbox,
                total: this.data.total,
                startIndex: this.data.startIndex,
                endIndex: this.data.endIndex,
                collapsed: this.collapsed
            };

            this.$el.html( this.template(data) );
            this.$('.idealist').append( list );

            this.chk = this.$('#messagelist-mainchk');
            this.renderThread();

            return this;
        },

        /**
         * Render the thread section
         */
        renderThread: function(){
            var list = document.createDocumentFragment();

            this.messageThread.each(function(message){
                var messageView = new MessageView({model:message});
                list.appendChild(messageView.render().el);
            });

            this.$('#messagelist-thread').empty().append(list);
        },

        /**
         * Blocks the panel
         */
        blockPanel: function(){
            this.$('.panel').addClass('is-loading');
        },

        /**
         * Unblocks the panel
         */
        unblockPanel: function(){
            this.$('.panel').removeClass('is-loading');
        },

        /**
         * Load the data
         */
        loadData: function(){
            var that = this,
                data = { 'page': this.data.page };

            this.blockPanel();
            this.collapsed = true;

            $.getJSON(  app.getApiUrl('posts'), data, function(data){
                that.data = data;
                that.messages.reset(data.posts);
            });
        },

        /**
         * Load the next data
         */
        loadNextData: function(){
            if( _.isNumber(this.data.page) ){
                this.data.page += 1;
            } else {
                this.data.page = 1;
            }

            if( this.data.page > this.data.maxPage ){
                this.data.page = this.data.maxPage;
            } else {
                this.loadData();
            }
        },

        /**
         * Load the previous data
         */
        loadPreviousData: function(){
            if( _.isNumber(this.data.page) ){
                this.data.page -= 1;
            } else {
                this.data.page = 1;
            }

            if( this.data.page < 1 ){
                this.data.page = 1;
            } else {
                this.loadData();
            }
        },

        /**
         * Close the panel
         */
        closePanel: function(){
            if( this.button ){
                this.button.trigger('click');
            }
        },

        /**
         * Collapse ALL messages
         */
        collapseMessages: function(){
            this.messages.each(function(message){
                message.attributes.isOpen = false;
            });

            this.collapsed = true;
            this.render();
        },

        /**
         * Expand ALL messages
         */
        expandMessages: function(){
            this.messages.each(function(message){
                message.attributes.isOpen = true;
            });

            this.collapsed = false;
            this.render();
        },

        /**
         * Open the message thread by the given id
         * @param  {String} id
         */
        openMessageByid: function(id){
            var message = this.messages.get(id);

            if( message ){
                message.set('read', true);
                this.loadThreadById(id);
            }
        },

        /**
         * Loads the message thread by post id
         * @param {Number} id
         */
        loadThreadById: function(id){
            var that = this;

            this.blockPanel();
            $.getJSON( app.getApiUrl('posts'), {'root_post_id': id}, function(json){
                that.unblockPanel();
                that.$el.addClass(MESSAGE_MODE);
                that.messageThread.reset(json.posts);
            });
        },

        /**
         * The events
         * @type {Object}
         */
        events: {
            'click .idealist-title': 'onTitleClick',
            'click #messageList-collapseButton': 'toggleMessages',
            'click #messagelist-returnButton': 'onReturnButtonClick',

            'click #messageList-prevButton': 'loadPreviousData',
            'click #messageList-nextButton': 'loadNextData',

            'change #messagelist-mainchk': 'onChangeMainCheckbox',
            'click #messagelist-selectall': 'selectAll',
            'click #messagelist-selectnone': 'selectNone',
            'click #messagelist-selectread': 'selectRead',
            'click #messagelist-selectunread': 'selectUnread',

            'click #messageList-closeButton': 'closePanel'
        },

        /**
         * @event
         */
        onTitleClick: function(ev){
            var id = ev.currentTarget.getAttribute('data-messageid');

            this.openMessageByid(id);
        },

        /**
         * Collapse or expand the ideas
         */
        toggleMessages: function(){
            if( this.collapsed ){
                this.expandMessages();
            } else {
                this.collapseMessages();
            }
        },

        /**
         * @event
         */
        onReturnButtonClick: function(ev){
            this.$el.removeClass(MESSAGE_MODE);
        },

        /**
         * @event
         */
        onChangeMainCheckbox: function(){
            var checked = this.chk.get(0).checked;

            this.messages.each(function(message){
                message.set('checked', checked);
            });
        },


        /**
         * @event
         */
        selectAll: function(){
            this.chk.get(0).checked = true;
            this.onChangeMainCheckbox();
        },

        /**
         * @event
         */
        selectNone: function(){
            this.chk.get(0).checked = false;
            this.onChangeMainCheckbox();
        },

        /**
         * @event
         */
        selectRead: function(){
            this.messages.each(function(message){
                var isRead = message.get('read');
                message.set('checked', isRead);
            });
        },

        /**
         * @event
         */
        selectUnread: function(){
            this.messages.each(function(message){
                var isUnread = !message.get('read');
                message.set('checked', isUnread);
            });
        }

    });

    return MessageList;
});
