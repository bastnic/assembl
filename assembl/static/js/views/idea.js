define(['backbone', 'underscore', 'jquery', 'models/idea', 'models/segment', 'app'],
function(Backbone, _, $, Idea, Segment, app){
    'use strict';

    var IdeaView = Backbone.View.extend({
        /**
         * Tag name
         * @type {String}
         */
        tagName: 'div',

        /**
         * The template
         * @type {[type]}
         */
        template: app.loadTemplate('idea'),

        /**
         * Counter used to open the idea when it is dragover
         * @type {Number}
         */
        dragOverCounter: 0,

        /**
         * @init
         */
        initialize: function(obj){
            if( _.isUndefined(this.model) ){
                this.model = new Idea.Model();
            }

            this.model.on('change:shortTitle change:longTitle change:segments', this.render, this);
            this.model.on('change:isSelected', this.onIsSelectedChange, this);
            this.model.on('replaced', this.onReplaced, this);
        },

        /**
         * The render
         * @return {IdeaView}
         */
        render: function(){
            app.trigger('render');

            var data = this.model.toJSON(),
                doc = document.createDocumentFragment();

            this.$el.addClass('idealist-item');

            this.onIsSelectedChange();

            if( data.isOpen === true ){
                this.$el.addClass('is-open');
            } else {
                this.$el.removeClass('is-open');
            }

            if( data.longTitle ){
                data.longTitle = ' - ' + data.longTitle.substr(0, 50);
            }

            data.children = this.model.getChildren();
            data.level = this.model.getLevel();
            data.segments = this.model.getSegments();

            this.$el.html(this.template(data));
            this.$('.idealist-children').append( this.getRenderedChildren(data.level) );
            return this;
        },

        /**
         * Returns all children rendered
         * @param {Number} parentLevel
         * @return {HTMLDivElement[]}
         */
        getRenderedChildren: function(parentLevel){
            var children = this.model.getChildren(),
                ret = [];

            children = _.sortBy(children, function(child){
                return child.get('order');
            });

            _.each(children, function(idea, i){
                idea.set('level', parentLevel + 1);

                var ideaView = new IdeaView({model:idea});
                ret.push( ideaView.render().el );
            });

            return ret;
        },

        /**
         * Show the childen
         */
        open: function(){
            this.model.set('isOpen', true);
            this.$el.addClass('is-open');
        },

        /**
         * Hide the childen
         */
        close: function(){
            this.model.set('isOpen', false);
            this.$el.removeClass('is-open');
        },

        /**
         * The events
         * @type {Object}
         */
        events: {
            'change [type="checkbox"]': 'onCheckboxChange',
            'click .idealist-title': 'onTitleClick',
            'click .idealist-arrow': 'toggle',

            'dragstart .idealist-body': 'onDragStart',
            'dragend .idealist-body': 'onDragEnd',

            'dragover .idealist-body': 'onDragOver',
            'dragleave .idealist-body': 'onDragLeave',
            'drop .idealist-body': 'onDrop'
        },

        /**
         * @event
         */
        onIsSelectedChange: function(){
            var value = this.model.get('isSelected');

            if( value === true ){
                this.$el.addClass('is-selected');
            } else {
                this.$el.removeClass('is-selected');
            }
        },

        /**
         * @event
         */
        onReplaced: function(newObject) {
            this.setElement(newObject);
            // TODO André: I'm sure this is overkill. Please optimize.
            app.ideaList.render();
            app.ideaPanel.idea = newObject;
            app.ideaPanel.render();
        },


        /**
         * @event
         */
        onCheckboxChange: function(ev){
            ev.stopPropagation();
            this.model.set('inSynthesis', ev.currentTarget.checked);
        },

        /**
         * @event
         * Select this idea as the current idea
         */
        onTitleClick: function(ev){
            ev.stopPropagation();
            if( this.model === app.getCurrentIdea() ){
                app.setCurrentIdea(null);
            } else {
                app.setCurrentIdea(this.model);
            }
        },

        /**
         * @event
         */
        onDragStart: function(ev){
            if( ev ){
                ev.stopPropagation();
            }

            ev.currentTarget.style.opacity = 0.4;
            ev.originalEvent.dataTransfer.effectAllowed = 'move';
            ev.originalEvent.dataTransfer.dropEffect = 'all';

            app.showDragbox(ev, this.model.get('shortTitle'));
            app.draggedIdea = this.model;
        },

        /**
         * @event
         */
        onDragEnd: function(ev){
            if( ev ){
                ev.preventDefault();
                ev.stopPropagation();
            }
            ev.currentTarget.style.opacity = '';
            app.draggedSegment = null;
        },

        /**
         * @event
         */
        onDragOver: function(ev){
            if( ev ){
                ev.preventDefault();
                ev.stopPropagation();
            }

            if( ev.originalEvent ){
                ev = ev.originalEvent;
            }

            if( this.dragOverCounter > 30 ){
                this.model.set('isOpen', true);
            }

            ev.dataTransfer.dropEffect = 'all';

            if( app.draggedIdea !== null ){

                // Do nothing if it is the same idea
                if( app.draggedIdea.cid === this.model.cid ){
                    ev.dataTransfer.dropEffect = 'none';
                    return;
                }

                // If it is a descendent, do nothing
                if( this.model.isDescendantOf(app.draggedIdea) ){
                    ev.dataTransfer.dropEffect = 'none';
                    return;
                }

                if( ev.target.classList.contains('idealist-abovedropzone') ){
                    this.$el.addClass('is-dragover-above');
                } else if( ev.target.classList.contains('idealist-dropzone') ){
                    this.$el.addClass('is-dragover-below');
                } else {
                    this.$el.addClass('is-dragover');
                }
            }

            if( app.draggedSegment !== null || app.draggedAnnotation !== null ){
                if( ev.target.classList.contains('idealist-dropzone') ){
                    this.$el.addClass('is-dragover-below');
                } else {
                    this.$el.addClass('is-dragover');
                }
            }

            this.dragOverCounter += 1;
        },

        /**
         * @event
         */
        onDragLeave: function(ev){
            if( ev ){
                ev.preventDefault();
                ev.stopPropagation();
            }

            this.dragOverCounter = 0;
            this.$el.removeClass('is-dragover is-dragover-above is-dragover-below');
        },

        /**
         * @event
         */
        onDrop: function(ev){
            if( ev ){
                ev.preventDefault();
                ev.stopPropagation();
            }

            var isDraggedBelow = this.$el.hasClass('is-dragover-below'),
                isDraggedAbove = this.$el.hasClass('is-dragover-above');

            this.$('.idealist-body').trigger('dragleave');

            var segment = app.getDraggedSegment();
            if( segment ){
                if( isDraggedBelow ){
                    // Add as a child
                    this.model.addSegmentAsChild(segment);
                } else {
                    // Add as a segment
                    this.model.addSegment(segment);
                }

                return;
            }

            var annotation = app.getDraggedAnnotation();
            if( annotation ){

                if( isDraggedBelow ){
                    // Add as a child
                    app.currentAnnotationIdea = this.model;
                    app.saveCurrentAnnotator();
                } else {
                    // Add as a segment
                    app.currentAnnotationIdIdea = this.model.get('id');
                    app.saveCurrentAnnotator();
                }
                
                return;
            }

            if( app.draggedIdea && app.draggedIdea.cid !== this.model.cid ){

                var idea = app.getDraggedIdea();

                // If it is a descendent, do nothing
                if( this.model.isDescendantOf(idea) ){
                    return;
                }

                if( isDraggedAbove ){
                    this.model.addSiblingAbove(idea);
                } else if ( isDraggedBelow ){
                    this.model.addSiblingBelow(idea);
                } else {
                    this.model.addChild(idea);
                }

            }
        },

        /**
         * Toggle show/hide an item
         * @event
         * @param  {Event} ev
         */
        toggle: function(ev){
            if( ev ){
                ev.preventDefault();
                ev.stopPropagation();
            }

            if( this.$el.hasClass('is-open') ){
                this.close();
            } else {
                this.open();
            }
        }

    });

    return IdeaView;
});
